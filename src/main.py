#!/usr/bin/env python3
"""
Main script for Twitter Bot

This module coordinates the Twitter bot's scheduled activities using the various
components: TwitterBot, TwitterAPI, ContentManager, and OpenAIIntegration.

It provides several run modes:
1. Scheduler - Run all tasks on a schedule (default)
2. OAuth server - Run the OAuth server for token acquisition
3. Single task execution - Run a specific task once and exit

Usage:
    # Run the scheduler (default)
    python main.py
    
    # Run the OAuth server for token acquisition
    python main.py --oauth
    
    # Run a single posting job
    python main.py --post
    
    # Run a single engagement job
    python main.py --engage
    
    # Run a single DM job
    python main.py --dm
    
    # Get bot status
    python main.py --status
    
    # Run token refresh
    python main.py --refresh-token
"""

import os
import sys
import logging
import time
import json
import random
import functools
import argparse
import threading
import subprocess
import traceback
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple, Union, Callable
from dotenv import load_dotenv

# Configure imports to work both as a module and as a script
try:
    # Try module-style imports first
    from src.twitter_bot import TwitterBot
    from src.twitter_api_interactions import TwitterAPI, run_auth_server
    from src.content_manager import ContentManager
    from src.ai_integration import OpenAIIntegration
    from src.dynamodb_integration import DynamoDBIntegration
    from src.regenerate_oauth2_token import main as regenerate_token
except ImportError:
    # Fallback to direct imports
    try:
        from twitter_bot import TwitterBot
        from twitter_api_interactions import TwitterAPI, run_auth_server
        from content_manager import ContentManager
        from ai_integration import OpenAIIntegration
        from dynamodb_integration import DynamoDBIntegration
        from src.regenerate_oauth2_token import main as regenerate_token
    except ImportError:
        # If direct imports fail, adjust the import path
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from src.twitter_bot import TwitterBot
        from src.twitter_api_interactions import TwitterAPI, run_auth_server
        from src.content_manager import ContentManager
        from src.ai_integration import OpenAIIntegration
        from src.dynamodb_integration import DynamoDBIntegration
        try:
            from src.regenerate_oauth2_token import main as regenerate_token
        except ImportError:
            # Last resort - regenerate_token might be at root level
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            from src.regenerate_oauth2_token import main as regenerate_token

# Load environment variables
load_dotenv()

# Configure logging
log_level = os.getenv('LOG_LEVEL', 'INFO')
log_file = os.getenv('MAIN_LOG_FILE', 'main.log')

numeric_level = getattr(logging, log_level.upper(), logging.INFO)

logging.basicConfig(
    level=numeric_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(), 
        logging.FileHandler(log_file)
    ]
)
logger = logging.getLogger("main")

# Check if running in AWS environment
is_aws_env = bool(os.getenv('AWS_EXECUTION_ENV', False))
if is_aws_env:
    logger.info("Running in AWS environment")

# Global components
BOT = None
TWITTER_API = None
CONTENT_MANAGER = None
AI = None
DB = None

# Last successful execution times
LAST_EXECUTIONS = {
    'post': None,
    'engage': None,
    'dm': None,
    'token_refresh': None
}

# Token refresh lock
token_refresh_lock = threading.Lock()

# Retry decorator for API calls
def retry(ExceptionToCheck, tries=3, delay=2, backoff=2, logger=None):
    """
    Retry decorator with exponential backoff.
    
    Args:
        ExceptionToCheck: Exception class or tuple of exception classes to catch
        tries: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff: Backoff multiplier (e.g. value of 2 will double the delay each retry)
        logger: Logger to use for logging retries
        
    Returns:
        A decorator function that wraps the original function with retry logic
    """
    def deco_retry(f):
        @functools.wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            last_exception = None
            
            while mtries > 0:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    last_exception = e
                    reset_time = None
                    
                    # Handle potential rate limit headers
                    if hasattr(e, 'response') and e.response:
                        reset_time = e.response.headers.get('x-rate-limit-reset')
                    
                    if reset_time:
                        # If rate limited, wait until the reset time
                        sleep_time = max(1, int(reset_time) - int(time.time()) + 5)
                        
                        if logger:
                            logger.warning(f"Rate limit reached in {f.__name__}. Sleeping for {sleep_time} seconds...")
                        else:
                            print(f"Rate limit reached in {f.__name__}. Sleeping for {sleep_time} seconds...")
                            
                        time.sleep(min(3600, sleep_time))  # Cap at 1 hour max sleep
                    else:
                        # Otherwise, use exponential backoff
                        mtries -= 1
                        
                        if mtries == 0:
                            if logger:
                                logger.error(f"Final retry failed in {f.__name__}: {e}")
                            else:
                                print(f"Final retry failed in {f.__name__}: {e}")
                            raise e
                        
                        if logger:
                            logger.warning(f"Error in {f.__name__}: {e}. Retrying in {mdelay} seconds... ({mtries} tries left)")
                        else:
                            print(f"Error in {f.__name__}: {e}. Retrying in {mdelay} seconds... ({mtries} tries left)")
                            
                        time.sleep(mdelay)
                        mdelay *= backoff
            
            # If we get here, we've exhausted all retries
            if last_exception:
                raise last_exception
            
            return f(*args, **kwargs)
        return f_retry
    return deco_retry

def update_env_file(updates, file_path='.env'):
    """
    Update the .env file with new values.
    
    Args:
        updates (dict): Dictionary of environment variables to update
        file_path (str): Path to the .env file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # First read the original file
        with open(file_path, 'r') as file:
            lines = file.readlines()
        
        # Update values
        updated_keys = set()
        updated_lines = []
        
        for line in lines:
            original_line = line
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                updated_lines.append(original_line)
                continue
            
            # Check for key=value pairs
            if '=' in line:
                key, _ = line.split('=', 1)
                key = key.strip()
                
                if key in updates:
                    updated_lines.append(f"{key}={updates[key]}\n")
                    updated_keys.add(key)
                    logger.info(f"Updated {key} in .env file")
                else:
                    updated_lines.append(original_line)
            else:
                updated_lines.append(original_line)
        
        # Add any keys that weren't found
        for key in updates:
            if key not in updated_keys:
                updated_lines.append(f"{key}={updates[key]}\n")
                logger.info(f"Added new key {key} to .env file")
        
        # Write updated file
        with open(file_path, 'w') as file:
            file.writelines(updated_lines)
        
        logger.info("Successfully updated .env file")
        return True
    
    except Exception as e:
        logger.error(f"Error updating .env file: {e}")
        return False

def initialize_components():
    """
    Initialize all the bot components.
    
    This function creates instances of the Twitter bot and its associated components,
    including the Twitter API client, content manager, and AI integration.
    
    Sets global variables for the components.
    
    Returns:
        tuple: A tuple containing the initialized components (bot, twitter_api, content_manager, ai)
    """
    global BOT, TWITTER_API, CONTENT_MANAGER, AI, DB
    
    logger.info("Initializing bot components")
    
    try:
        # Initialize the TwitterAPI first (for token management)
        if TWITTER_API is None:
            TWITTER_API = TwitterAPI()
            logger.info("Twitter API initialized")
        
        # Check OAuth token
        if not check_oauth_token():
            logger.warning("OAuth token needs refresh. Attempting to refresh...")
            refresh_token()
            
            # Check again after refresh
            if not check_oauth_token():
                logger.error("OAuth token still invalid after refresh")
            else:
                logger.info("OAuth token refreshed successfully")
        
        # Initialize other components
        if CONTENT_MANAGER is None:
            CONTENT_MANAGER = ContentManager()
            logger.info("Content Manager initialized")
        
        if AI is None:
            AI = OpenAIIntegration()
            logger.info("OpenAI integration initialized")
        
        if DB is None:
            DB = DynamoDBIntegration()
            logger.info("DynamoDB integration initialized")
        
        # Initialize the TwitterBot which will use all other components
        if BOT is None:
            BOT = TwitterBot()
            logger.info("Twitter Bot initialized")
        
        logger.info("All bot components initialized successfully")
        return BOT, TWITTER_API, CONTENT_MANAGER, AI
        
    except Exception as e:
        logger.critical(f"Error initializing components: {str(e)}")
        logger.critical(traceback.format_exc())
        raise

def refresh_token():
    """
    Refresh the OAuth 2.0 token directly.
    
    This function calls the regenerate_token function from the imported module,
    avoiding the need to execute an external script.
    
    Returns:
        bool: True if the token was successfully refreshed, False otherwise
    """
    global LAST_EXECUTIONS, TWITTER_API
    
    # Use lock to prevent concurrent token refreshes
    with token_refresh_lock:
        logger.info("Starting OAuth token refresh")
        
        try:
            # Call the imported regenerate_token function
            result = regenerate_token()
            
            if result:
                logger.info("OAuth token refreshed successfully via direct call")
                
                # CRITICAL FIX: Reload environment variables to update in-memory values
                load_dotenv(override=True)
                
                # CRITICAL FIX: Update the TwitterAPI instance directly
                if TWITTER_API:
                    TWITTER_API.oauth2_token = os.getenv('OAUTH_2_ACCESS_TOKEN')
                    TWITTER_API.token_expiry = float(os.getenv('TWITTER_TOKEN_EXPIRY', '0'))
                    logger.info(f"Updated TwitterAPI instance with new token. Expires at: {datetime.fromtimestamp(TWITTER_API.token_expiry)}")
                
                # Update last execution time
                LAST_EXECUTIONS['token_refresh'] = datetime.now()
                
                return True
            else:
                logger.error("Direct token refresh failed, trying subprocess approach")
                
                # Try the subprocess approach as a fallback
                try:
                    logger.info("Attempting token refresh via subprocess")
                    # Use subprocess.run instead of os.system for better error handling
                    result = subprocess.run(
                        [sys.executable, 'regenerate_oauth2_token.py'],
                        capture_output=True,
                        text=True
                    )
                    
                    if result.returncode == 0:
                        logger.info(f"Token refresh via subprocess succeeded: {result.stdout.strip()}")
                        
                        # CRITICAL FIX: Reload .env file to get updated token
                        load_dotenv(override=True)
                        
                        # CRITICAL FIX: Update the TwitterAPI instance directly
                        if TWITTER_API:
                            TWITTER_API.oauth2_token = os.getenv('OAUTH_2_ACCESS_TOKEN')
                            TWITTER_API.token_expiry = float(os.getenv('TWITTER_TOKEN_EXPIRY', '0'))
                            logger.info(f"Updated TwitterAPI instance with new token from subprocess. Expires at: {datetime.fromtimestamp(TWITTER_API.token_expiry)}")
                        
                        # Update last execution time
                        LAST_EXECUTIONS['token_refresh'] = datetime.now()
                        return True
                    else:
                        logger.error(f"Token refresh via subprocess failed: {result.stderr.strip()}")
                        return False
                        
                except Exception as sub_e:
                    logger.error(f"Subprocess token refresh failed: {str(sub_e)}")
                    logger.error(traceback.format_exc())
                    return False
        except Exception as e:
            logger.error(f"Error refreshing OAuth token: {str(e)}")
            logger.error(traceback.format_exc())
            return False
        
@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def scheduled_post():
    """
    Scheduled task to post tweets with images.
    
    This function gets content from the content manager, generates tweet text
    using AI, and posts it to Twitter.
    
    Returns:
        bool: True if successful, False otherwise
    """
    global LAST_EXECUTIONS, TWITTER_API, CONTENT_MANAGER, AI
    logger.info("Scheduled post started")
    
    try:
        # Ensure components are initialized
        initialize_components()
        
        # CRITICAL FIX: Force reload of tokens from environment
        logger.info("Reloading tokens from environment before posting")
        TWITTER_API.reload_tokens_from_env()
        
        # Check token
        if not check_oauth_token():
            logger.warning("OAuth token expired, refreshing")
            refresh_token()
            
            # Bail out if token refresh failed
            if not check_oauth_token():
                logger.error("OAuth token refresh failed, aborting scheduled post")
                return False
        
        # Get content for posting
        content = CONTENT_MANAGER.get_next_content_for_posting()
        
        if not content:
            logger.warning("No content available for posting")
            return False
        
        image_path = content.get('image_path')
        summary = content.get('summary')
        folder_name = content.get('folder_name', 'unknown')
        
        logger.info(f"Selected content from folder: {folder_name}")
        logger.info(f"Image path: {image_path}")
        
        # Validate image path
        if not os.path.exists(image_path):
            logger.error(f"Image file not found: {image_path}")
            # Mark as posted so we don't try to use it again
            CONTENT_MANAGER.mark_content_as_posted(content.get('id'))
            return False
        
        # Generate tweet text using AI
        logger.info("Generating tweet text with AI")
        tweet_text = AI.generate_tweet_text(image_path, summary)
        logger.info(f"Generated tweet text: {tweet_text}")
        
        # Post tweet with image
        logger.info(f"Posting tweet with image: {os.path.basename(image_path)}")
        result = TWITTER_API.post_tweet_with_media(tweet_text, image_path)
        
        if result:
            # Extract tweet ID
            tweet_id = result.get('data', {}).get('id', 'unknown')
            logger.info(f"Tweet posted successfully! Tweet ID: {tweet_id}")
            
            # Mark content as posted
            CONTENT_MANAGER.mark_content_as_posted(content.get('id'))
            
            # Save posting history if we have the DB method
            if hasattr(DB, 'save_posting_history'):
                DB.save_posting_history({
                    'content_id': content.get('id'),
                    'tweet_id': tweet_id,
                    'timestamp': datetime.now().isoformat(),
                    'status': 'posted'
                })
            
            # Update last execution time
            LAST_EXECUTIONS['post'] = datetime.now()
            
            logger.info("Scheduled post completed successfully")
            return True
        else:
            logger.error("Failed to post tweet")
            return False
            
    except Exception as e:
        logger.error(f"Error in scheduled post: {str(e)}")
        logger.error(traceback.format_exc())
        return False

@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def monitor_and_engage():
    """
    Scheduled task to monitor hashtags and engage with users.
    
    This function uses the TwitterBot to find users, search for keywords in their
    tweets, and engage with them through likes, retweets, comments.
    
    Returns:
        dict: A dictionary containing engagement counts
    """
    global LAST_EXECUTIONS
    logger.info("Monitor and engage started")
    results = {}
    
    try:
        # Ensure components are initialized
        initialize_components()
        
        # Check token
        if not check_oauth_token():
            logger.warning("OAuth token expired, refreshing")
            refresh_token()
            
            # Bail out if token refresh failed
            if not check_oauth_token():
                logger.error("OAuth token refresh failed, aborting monitor and engage")
                return results
        
        # Find and store users based on hashtags
        logger.info("Finding and storing users based on hashtags")
        users_found = BOT.find_and_store_users()
        results['users_found'] = users_found
        
        # Search for keywords in stored users' tweets
        logger.info("Searching for keywords in users' tweets")
        keyword_matches = BOT.search_keywords_in_tweets()
        results['keyword_matches'] = keyword_matches
        
        # Engage with users
        logger.info("Engaging with users through likes, retweets, and comments")
        engagement_results = BOT.engage_with_users()
        results.update(engagement_results)
        
        # Update last execution time
        LAST_EXECUTIONS['engage'] = datetime.now()
        
        logger.info(f"Monitor and engage completed successfully: {json.dumps(results)}")
        return results
        
    except Exception as e:
        logger.error(f"Error in monitor and engage: {str(e)}")
        logger.error(traceback.format_exc())
        return results

@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def send_scheduled_dms():
    """
    Scheduled task to send DMs to users.
    
    Returns:
        int: Number of DMs sent
    """
    global LAST_EXECUTIONS
    logger.info("Scheduled DM sending started")
    
    try:
        # Ensure components are initialized
        initialize_components()
        
        # Check token
        if not check_oauth_token():
            logger.warning("OAuth token expired, refreshing")
            refresh_token()
            
            # Bail out if token refresh failed
            if not check_oauth_token():
                logger.error("OAuth token refresh failed, aborting DM sending")
                return 0
        
        # Send DMs to users
        dms_sent = BOT.send_dms_to_users()
        
        # Update last execution time
        LAST_EXECUTIONS['dm'] = datetime.now()
        
        logger.info(f"Scheduled DM sending completed successfully. DMs sent: {dms_sent}")
        return dms_sent
        
    except Exception as e:
        logger.error(f"Error in scheduled DM sending: {str(e)}")
        logger.error(traceback.format_exc())
        return 0

def check_oauth_token():
    """
    Check if OAuth token needs refresh.
    
    Returns:
        bool: True if token is valid, False if it needs refresh
    """
    try:
        # First try to use the global TWITTER_API instance
        if TWITTER_API is not None and hasattr(TWITTER_API, 'token_expiry'):
            token_expiry = TWITTER_API.token_expiry
        else:
            # Get token expiry from environment
            token_expiry_env = os.getenv('TWITTER_TOKEN_EXPIRY', os.getenv('TOKEN_EXPIRY', '0'))
            try:
                token_expiry = float(token_expiry_env)
            except ValueError:
                logger.error(f"Invalid token expiry value: {token_expiry_env}")
                return False
        
        # Check if token is expired or about to expire
        current_time = time.time()
        expiry_buffer = int(os.getenv('TOKEN_EXPIRY_BUFFER_SECONDS', '300'))  # 5 minutes by default
        
        if token_expiry - current_time < expiry_buffer:
            # Format the time nicely for logging
            if token_expiry <= current_time:
                expired_ago = current_time - token_expiry
                logger.warning(f"OAuth token expired {expired_ago:.1f} seconds ago")
            else:
                expires_in = token_expiry - current_time
                logger.warning(f"OAuth token expires in {expires_in:.1f} seconds (buffer: {expiry_buffer}s)")
            return False
        
        # Token is valid - calculate time until expiry
        expires_in = token_expiry - current_time
        expires_in_minutes = expires_in / 60
        expiry_time = datetime.fromtimestamp(token_expiry).strftime('%Y-%m-%d %H:%M:%S')
        
        logger.debug(f"OAuth token is valid for {expires_in_minutes:.1f} minutes (until {expiry_time})")
        return True
        
    except Exception as e:
        logger.error(f"Error checking OAuth token: {str(e)}")
        logger.error(traceback.format_exc())
        return False

def run_scheduler():
    """
    Run the scheduler for periodic tasks.
    
    This function creates a scheduler and adds jobs for content posting,
    monitoring, and DM sending.
    """
    # Initialize components first
    initialize_components()
    
    try:
        # Import scheduling library
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
        
        # Create scheduler - use process pool executor for AWS compatibility
        job_defaults = {
            'coalesce': True,
            'max_instances': 1,
            'misfire_grace_time': 3600  # 1 hour
        }
        
        if is_aws_env:
            # Use settings more suitable for AWS Lambda/ECS
            scheduler = BlockingScheduler(job_defaults=job_defaults)
            logger.info("Created AWS-optimized scheduler")
        else:
            # Standard scheduler for non-AWS environments
            scheduler = BlockingScheduler(job_defaults=job_defaults)
            logger.info("Created standard scheduler")
        
        # Define job listener function
        def job_listener(event):
            """Event listener for scheduler jobs."""
            if event.exception:
                logger.error(f"Job {event.job_id} failed with error: {event.exception}")
                logger.error(f"Traceback: {event.traceback}")
            else:
                logger.info(f"Job {event.job_id} completed successfully: {event.retval}")
        
        # Add listener for job events
        scheduler.add_listener(job_listener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
        
        # Load intervals from env variables
        posting_interval = int(os.getenv('POSTING_INTERVAL_HOURS', 24))
        engagement_interval = int(os.getenv('ENGAGEMENT_INTERVAL_HOURS', 6))
        token_refresh_interval = int(os.getenv('TOKEN_REFRESH_INTERVAL_HOURS', 12))
        
        # Calculate first runs with jitter to avoid clustering
        post_jitter = random.randint(1, 10) * 60  # 1-10 minutes
        engage_jitter = random.randint(1, 30) * 60  # 1-30 minutes
        
        # Add scheduled posting job
        scheduler.add_job(
            scheduled_post, 
            'interval', 
            hours=posting_interval,
            id='content_posting',
            name='Content Posting',
            next_run_time=datetime.now() + timedelta(seconds=post_jitter)
        )
        
        # Add monitoring and engagement job
        scheduler.add_job(
            monitor_and_engage, 
            'interval', 
            hours=engagement_interval,
            id='monitoring_engagement',
            name='Monitoring and Engagement',
            next_run_time=datetime.now() + timedelta(seconds=engage_jitter)
        )
        
        # Add DM sending job - Twice a week (Monday and Thursday by default)
        dm_schedule = os.getenv('DM_SCHEDULE', 'mon,thu')
        dm_hour = int(os.getenv('DM_HOUR', 15))  # 3 PM by default
        
        scheduler.add_job(
            send_scheduled_dms, 
            CronTrigger(day_of_week=dm_schedule, hour=dm_hour),
            id='dm_sending',
            name='DM Sending'
        )
        
        # Add token refresh job - critical for continued operation
        scheduler.add_job(
            refresh_token,
            'interval',
            hours=token_refresh_interval,
            id='token_refresh',
            name='Token Refresh',
            next_run_time=datetime.now() + timedelta(minutes=30)  # Start token refresh after 30 minutes
        )
        
        # Log scheduled jobs
        logger.info("Starting scheduler with the following jobs:")
        for job in scheduler.get_jobs():
            if hasattr(job, 'next_run_time'):
                logger.info(f"- {job.name}: Next run at {job.next_run_time}")
            else:
                logger.info(f"- {job.name}: Next run time will be calculated when scheduler starts")
        
        # Start the scheduler
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped by user")
            sys.exit(0)
            
    except ImportError:
        logger.critical("APScheduler library not found. Please install it with: pip install apscheduler")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Error starting scheduler: {str(e)}")
        logger.critical(traceback.format_exc())
        sys.exit(1)

def show_status():
    """
    Display the current status of the Twitter bot components.
    """
    try:
        # Initialize components
        initialize_components()
        
        # Get basic status from TwitterBot
        status = BOT.get_status()
        
        # Add scheduler information
        status['scheduler'] = {
            'posting_interval': int(os.getenv('POSTING_INTERVAL_HOURS', 24)),
            'engagement_interval': int(os.getenv('ENGAGEMENT_INTERVAL_HOURS', 6)),
            'token_refresh_interval': int(os.getenv('TOKEN_REFRESH_INTERVAL_HOURS', 12)),
            'dm_schedule': os.getenv('DM_SCHEDULE', 'mon,thu'),
            'dm_hour': int(os.getenv('DM_HOUR', 15))
        }
        
        # Add content information
        available_content = CONTENT_MANAGER.list_available_content()
        total_local = len(available_content.get('local', []))
        total_s3 = len(available_content.get('s3', []))
        
        status['content'] = {
            'total_local_available': total_local,
            'total_s3_available': total_s3,
            'total_available': total_local + total_s3
        }
        
        # Add last execution times
        status['last_executions'] = {}
        for task, last_time in LAST_EXECUTIONS.items():
            if last_time:
                status['last_executions'][task] = last_time.isoformat()
            else:
                status['last_executions'][task] = "Never executed"
        
        # Add OAuth token information
        token_expiry = 0
        if TWITTER_API and hasattr(TWITTER_API, 'token_expiry'):
            token_expiry = TWITTER_API.token_expiry
        else:
            token_expiry_str = os.getenv('TWITTER_TOKEN_EXPIRY', os.getenv('TOKEN_EXPIRY', '0'))
            try:
                token_expiry = float(token_expiry_str)
            except ValueError:
                pass
                
        if token_expiry > 0:
            current_time = time.time()
            expires_in = max(0, token_expiry - current_time)
            status['oauth_token'] = {
                'valid': expires_in > 0,
                'expires_in_seconds': expires_in,
                'expires_in_minutes': expires_in / 60,
                'expiry_time': datetime.fromtimestamp(token_expiry).isoformat()
            }
        else:
            status['oauth_token'] = {
                'valid': False,
                'expires_in_seconds': 0,
                'expires_in_minutes': 0,
                'expiry_time': 'Unknown'
            }
        
        # Add AWS environment information if applicable
        if is_aws_env:
            status['aws'] = {
                'environment': os.getenv('AWS_EXECUTION_ENV', 'Unknown'),
                'region': os.getenv('AWS_REGION', 'Unknown')
            }
        
        # Add version information
        status['version'] = {
            'timestamp': datetime.now().isoformat(),
            'python': sys.version
        }
        
        # Print status information
        print(json.dumps(status, indent=2))
        
        # Return status in case it's needed
        return status
        
    except Exception as e:
        logger.error(f"Error showing status: {str(e)}")
        logger.error(traceback.format_exc())
        print(json.dumps({
            'error': str(e),
            'traceback': traceback.format_exc(),
            'timestamp': datetime.now().isoformat()
        }, indent=2))
        sys.exit(1)

if __name__ == "__main__":
    # Set up argument parser with more descriptive help
    parser = argparse.ArgumentParser(
        description='Twitter Bot main script',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                     # Run the scheduler
  python main.py --oauth             # Run the OAuth server for token acquisition
  python main.py --post              # Run a single posting job
  python main.py --engage            # Run a single engagement job
  python main.py --dm                # Run a single DM job
  python main.py --status            # Show bot status
  python main.py --refresh-token     # Refresh the OAuth token
        """
    )
    
    parser.add_argument('--oauth', action='store_true', help='Run the OAuth server for token acquisition')
    parser.add_argument('--post', action='store_true', help='Run a single post job and exit')
    parser.add_argument('--engage', action='store_true', help='Run a single engagement job and exit')
    parser.add_argument('--dm', action='store_true', help='Run a single DM job and exit')
    parser.add_argument('--scheduler', action='store_true', help='Run the scheduler (default if no args provided)')
    parser.add_argument('--status', action='store_true', help='Show the current status of the bot')
    parser.add_argument('--refresh-token', action='store_true', help='Refresh the OAuth token')
    
    args = parser.parse_args()
    
    # Log start information
    start_time = datetime.now()
    logger.info(f"Twitter Bot Main Script started at {start_time.isoformat()}")
    print(f"Twitter Bot starting at {start_time.isoformat()}")
    
    try:
        if args.oauth:
            # Run the OAuth server for token acquisition
            logger.info("Starting OAuth server for token acquisition")
            print("Starting OAuth server for token acquisition")
            print("Please open the URL provided in your browser to authenticate")
            run_auth_server()
            
        elif args.status:
            # Show bot status
            print("Getting bot status...")
            show_status()
            
        elif args.refresh_token:
            # Refresh OAuth token
            print("Refreshing OAuth token...")
            success = refresh_token()
            print(f"Token refresh {'succeeded' if success else 'failed'}")
            sys.exit(0 if success else 1)
            
        elif args.post:
            # Run a single posting job
            print("Running single post job...")
            result = scheduled_post()
            print(f"Post job {'succeeded' if result else 'failed'}")
            sys.exit(0 if result else 1)
            
        elif args.engage:
            # Run a single engagement job
            print("Running single engagement job...")
            result = monitor_and_engage()
            print(f"Engagement job completed with results: {json.dumps(result)}")
            sys.exit(0 if result else 1)
            
        elif args.dm:
            # Run a single DM job
            print("Running single DM job...")
            dms_sent = send_scheduled_dms()
            print(f"DM job completed. {dms_sent} DMs sent.")
            sys.exit(0 if dms_sent > 0 else 1)
            
        else:
            # Default to running the scheduler
            print("Starting bot scheduler...")
            run_scheduler()
            
    except Exception as e:
        logger.critical(f"Unhandled exception in main: {str(e)}")
        logger.critical(traceback.format_exc())
        print(f"Critical error: {str(e)}")
        sys.exit(1)