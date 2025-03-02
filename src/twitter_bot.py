"""
Twitter Bot Core Implementation

This module contains the main TwitterBot class that orchestrates the entire bot workflow,
integrating Twitter API interactions, content management, AI generation, and database operations.

The bot performs several key functions:
1. Finding and storing users based on hashtags
2. Searching for keywords in stored users' tweets
3. Engaging with users through likes, retweets, and comments
4. Posting tweets with images
5. Sending DMs to relevant users

Usage:
    bot = TwitterBot()
    bot.run()  # Run the complete workflow
    
    # Or run individual components:
    bot.find_and_store_users()
    bot.search_keywords_in_tweets()
    bot.engage_with_users()
    bot.post_tweets_with_images()
    bot.send_dms_to_users()
"""

import os
import logging
import time
import random
import sys
import json
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union, Tuple
from dotenv import load_dotenv

# Import custom modules - use absolute imports for reliability
try:
    from src.twitter_api_interactions import TwitterAPI
    from src.dynamodb_integration import DynamoDBIntegration
    from src.ai_integration import OpenAIIntegration
    from src.content_manager import ContentManager
except ImportError:
    # Fall back to direct imports if not in a package
    from twitter_api_interactions import TwitterAPI
    from dynamodb_integration import DynamoDBIntegration
    from ai_integration import OpenAIIntegration
    from content_manager import ContentManager

# Load environment variables from .env file
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    log_file = os.getenv('MAIN_LOG_FILE', 'main.log')
    
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

class TwitterBot:
    """
    Main Twitter Bot class that orchestrates all the bot's functionality.
    
    This class integrates various components (Twitter API, OpenAI, content management,
    database operations) to create a complete Twitter bot that can discover users,
    engage with their content, post original content, and send personalized messages.
    
    Attributes:
        twitter (TwitterAPI): Handler for Twitter API interactions
        ai (OpenAIIntegration): Handler for AI text generation
        content_manager (ContentManager): Handler for content selection and tracking
        db (DynamoDBIntegration): Handler for database operations
        target_hashtags (List[str]): List of hashtags to target
        target_keywords (List[str]): List of keywords to look for in tweets
        min_followers (int): Minimum followers required for targeting a user
        min_profile_age_days (int): Minimum account age in days
        min_tweet_count (int): Minimum number of tweets required
        max_engagement_age_days (int): Maximum age of tweets to engage with
    """
    
    def __init__(self):
        """Initialize the Twitter Bot with all required components."""
        logger.info("Initializing Twitter Bot")
        
        # Initialize API clients and components
        try:
            self.twitter = TwitterAPI()
            self.ai = OpenAIIntegration()
            self.content_manager = ContentManager()
            self.db = DynamoDBIntegration()
            
            # Log initialization success for components
            logger.info("Twitter API initialized")
            logger.info("OpenAI integration initialized")
            logger.info("Content Manager initialized")
            logger.info("DynamoDB integration initialized")
            
            # Load configuration from environment variables with sensible defaults
            self.target_hashtags = self._get_env_list('TARGET_HASHTAGS', 'Kickstarter,crowdfunding')
            self.target_keywords = self._get_env_list('TARGET_KEYWORDS', 'Kickstarter campaign,comic,art')
            self.min_followers = int(os.getenv('MIN_FOLLOWERS', 50))
            self.min_profile_age_days = int(os.getenv('MIN_PROFILE_AGE_DAYS', 30))
            self.min_tweet_count = int(os.getenv('MIN_TWEET_COUNT', 20))
            self.max_engagement_age_days = int(os.getenv('MAX_ENGAGEMENT_AGE_DAYS', 7))
            
            # Track last execution times
            self.last_execution = {
                'find_users': datetime.min,
                'search_keywords': datetime.min,
                'engage': datetime.min,
                'post': datetime.min,
                'dm': datetime.min
            }
            
            logger.info(f"Targeting hashtags: {self.target_hashtags}")
            logger.info(f"Targeting keywords: {self.target_keywords}")
            logger.info(f"User criteria: {self.min_followers}+ followers, {self.min_profile_age_days}+ days old, {self.min_tweet_count}+ tweets")
            logger.info(f"Bot initialized successfully")
            
        except Exception as e:
            logger.critical(f"Error initializing Twitter Bot: {str(e)}")
            logger.critical(traceback.format_exc())
            raise
    
    def _get_env_list(self, env_var: str, default: str) -> List[str]:
        """
        Helper method to get a list from an environment variable.
        
        Args:
            env_var (str): Name of the environment variable
            default (str): Default value if the variable is not set
            
        Returns:
            List[str]: List of values from the environment variable
        """
        value = os.getenv(env_var, default)
        result = [item.strip() for item in value.split(',') if item.strip()]
        logger.debug(f"Loaded {env_var}: {result}")
        return result
    
    def run(self) -> bool:
        """
        Main bot execution loop that runs all component functions.
        
        This method executes the complete workflow of the bot:
        1. Find and store users based on hashtags
        2. Search for keywords in stored users' tweets
        3. Engage with users through likes, retweets, comments
        4. Post tweets with images
        5. Send DMs to relevant users
        
        Returns:
            bool: True if execution completed successfully, False otherwise
        """
        start_time = time.time()
        logger.info("Starting bot execution")
        
        success = True
        results = {}
        try:
            # Verify and refresh OAuth2 token before operations
            logger.info("Checking OAuth2 token status")
            token_valid = self.twitter.refresh_oauth2_token_if_needed()
            if not token_valid:
                logger.warning("OAuth2 token refresh failed, but continuing with execution")
            
            # 1. Find and store users based on hashtags
            logger.info("Step 1: Finding and storing users")
            results['users_found'] = self.find_and_store_users()
            self.last_execution['find_users'] = datetime.now()
            
            # 2. Search for keywords in stored users' tweets
            logger.info("Step 2: Searching for keywords in tweets")
            results['keywords_found'] = self.search_keywords_in_tweets()
            self.last_execution['search_keywords'] = datetime.now()
            
            # 3. Engage with users (like, retweet, comment)
            logger.info("Step 3: Engaging with users")
            results['engagement'] = self.engage_with_users()
            self.last_execution['engage'] = datetime.now()
            
            # 4. Post tweets with images
            logger.info("Step 4: Posting tweets with images")
            results['tweet_posted'] = self.post_tweets_with_images()
            self.last_execution['post'] = datetime.now()
            
            # 5. Send DMs to relevant users
            logger.info("Step 5: Sending DMs to users")
            results['dms_sent'] = self.send_dms_to_users()
            self.last_execution['dm'] = datetime.now()
            
            elapsed_time = time.time() - start_time
            logger.info(f"Bot execution completed successfully in {elapsed_time:.2f} seconds")
            logger.info(f"Results summary: {json.dumps(results)}")
            
            return True
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"Error in main execution after {elapsed_time:.2f} seconds: {str(e)}")
            logger.error(traceback.format_exc())
            success = False
            
            # Try to log a summary of what completed successfully
            logger.info(f"Partial results before error: {json.dumps(results)}")
            return False
        finally:
            # Always log a completion message
            logger.info(f"Bot run finished with status: {'SUCCESS' if success else 'FAILURE'}")
    
    def find_and_store_users(self) -> int:
        """
        Find users based on hashtags and filter them based on criteria.
        
        This method searches for recent tweets with the target hashtags,
        filters users based on criteria like follower count and profile age,
        and stores them in the database for further processing.
        
        Returns:
            int: Number of new users found and stored
        """
        logger.info("Finding and storing users based on hashtags")
        users_stored = 0
        
        # Track hashtag stats for reporting
        hashtag_stats = {hashtag: 0 for hashtag in self.target_hashtags}
        
        for hashtag in self.target_hashtags:
            logger.info(f"Searching for users with hashtag: #{hashtag}")
            
            try:
                # Search for tweets with this hashtag
                tweets = self.twitter.search_recent_tweets(hashtag, max_results=100)
                
                if 'data' not in tweets:
                    logger.warning(f"No tweets found for hashtag: #{hashtag}")
                    continue
                
                tweet_count = len(tweets.get('data', []))
                logger.info(f"Found {tweet_count} tweets with hashtag: #{hashtag}")
                
                # Get user information from expansions
                users_dict = {}
                if 'includes' in tweets and 'users' in tweets['includes']:
                    for user in tweets['includes']['users']:
                        users_dict[user['id']] = user
                    logger.debug(f"Loaded {len(users_dict)} user details from expansions")
                
                for tweet in tweets.get('data', []):
                    user_id = tweet.get('author_id')
                    
                    # Skip if no user ID
                    if not user_id:
                        logger.debug("Tweet missing author_id, skipping")
                        continue
                    
                    # Skip if user is already in our database
                    if self.db.user_exists(user_id):
                        logger.debug(f"User {user_id} already exists in database, skipping")
                        continue
                    
                    # Get user details - first check if we have it in the expansions
                    user = users_dict.get(user_id)
                    
                    # If not in expansions, get from API
                    if not user:
                        user_data = self.twitter.get_user_by_id(user_id)
                        if 'data' not in user_data:
                            logger.debug(f"No user data found for user ID: {user_id}")
                            continue
                        user = user_data.get('data', {})
                    
                    # Check if user exists and meets criteria
                    if user and self._user_meets_criteria(user):
                        # Calculate profile age
                        created_at = datetime.strptime(user.get('created_at', ''), "%Y-%m-%dT%H:%M:%S.%fZ")
                        profile_age_days = (datetime.now() - created_at).days
                        
                        # Store user in database
                        user_info = {
                            'UserID': user_id,
                            'Username': user.get('username', ''),
                            'FollowerCount': user.get('public_metrics', {}).get('followers_count', 0),
                            'ProfileAge': profile_age_days,
                            'TweetCount': user.get('public_metrics', {}).get('tweet_count', 0),
                            'ProfileCreatedAt': user.get('created_at', ''),
                            'HashtagsUsed': [hashtag],
                            'LastEngagementDate': datetime.now().isoformat()
                        }
                        
                        success = self.db.store_user_data(user_info)
                        if success:
                            users_stored += 1
                            hashtag_stats[hashtag] += 1
                            logger.info(f"Stored user: @{user.get('username', '')} with {user_info['FollowerCount']} followers")
                        else:
                            logger.warning(f"Failed to store user: @{user.get('username', '')}")
                
                # Apply rate limit-friendly delay between hashtags
                if len(self.target_hashtags) > 1:
                    delay = random.uniform(5, 15)
                    logger.debug(f"Applying delay of {delay:.2f} seconds between hashtags")
                    time.sleep(delay)
            
            except Exception as e:
                logger.error(f"Error finding users for hashtag #{hashtag}: {str(e)}")
                logger.debug(traceback.format_exc())
                # Continue with next hashtag rather than stopping completely
        
        # Log detailed stats by hashtag
        for hashtag, count in hashtag_stats.items():
            logger.info(f"Hashtag #{hashtag}: {count} new users stored")
        
        logger.info(f"Total new users stored: {users_stored}")
        return users_stored
    
    def _user_meets_criteria(self, user: Dict[str, Any]) -> bool:
        """
        Check if a user meets all required criteria for targeting.
        
        Args:
            user (Dict[str, Any]): User data dictionary from Twitter API
            
        Returns:
            bool: True if user meets all criteria, False otherwise
        """
        try:
            username = user.get('username', 'unknown')
            logger.debug(f"Checking criteria for user: @{username}")
            
            # Check followers count
            followers_count = user.get('public_metrics', {}).get('followers_count', 0)
            if followers_count < self.min_followers:
                logger.debug(f"User @{username} has insufficient followers: {followers_count} < {self.min_followers}")
                return False
            
            # Check profile age
            try:
                created_at = datetime.strptime(user.get('created_at', ''), "%Y-%m-%dT%H:%M:%S.%fZ")
                profile_age_days = (datetime.now() - created_at).days
                if profile_age_days < self.min_profile_age_days:
                    logger.debug(f"User @{username} has insufficient profile age: {profile_age_days} < {self.min_profile_age_days} days")
                    return False
            except (ValueError, TypeError) as e:
                logger.warning(f"Error calculating profile age for @{username}: {str(e)}")
                return False
            
            # Check tweet count
            tweet_count = user.get('public_metrics', {}).get('tweet_count', 0)
            if tweet_count < self.min_tweet_count:
                logger.debug(f"User @{username} has insufficient tweets: {tweet_count} < {self.min_tweet_count}")
                return False
            
            # Check recent engagement - if we have user ID
            user_id = user.get('id')
            if user_id:
                try:
                    has_recent_engagement = self.twitter.check_user_recent_engagement(
                        user_id, 
                        days=self.max_engagement_age_days
                    )
                    if not has_recent_engagement:
                        logger.debug(f"User @{username} has no recent engagement within {self.max_engagement_age_days} days")
                        return False
                except Exception as e:
                    # Log but don't fail the check, as this is just an optional enhancement
                    logger.warning(f"Error checking recent engagement for @{username}: {str(e)}")
            
            logger.info(f"User @{username} meets all criteria: {followers_count} followers, {profile_age_days} days old, {tweet_count} tweets")
            return True
            
        except Exception as e:
            logger.error(f"Error checking user criteria: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
    
    def search_keywords_in_tweets(self) -> int:
        """
        Search for keywords in stored users' tweets.
        
        This method retrieves users from the database, gets their recent tweets,
        and searches for target keywords in those tweets.
        
        Returns:
            int: Number of keyword matches found
        """
        logger.info("Searching for keywords in users' tweets")
        keyword_matches = 0
        
        # Get users from DynamoDB - use our db instance
        try:
            # Get users who haven't been checked for keywords recently
            users = self._get_users_for_keyword_search()
            logger.info(f"Retrieved {len(users)} users for keyword search")
            
            # Track keyword stats
            keyword_stats = {keyword: 0 for keyword in self.target_keywords}
            
            for user in users:
                try:
                    user_id = user.get('UserID')
                    username = user.get('Username', '')
                    
                    logger.info(f"Searching tweets of user: @{username}")
                    
                    # Get user's tweets
                    tweets = self.twitter.get_user_tweets(user_id, max_results=50)
                    
                    if 'data' not in tweets:
                        logger.debug(f"No tweets found for user: @{username}")
                        continue
                    
                    tweet_count = len(tweets.get('data', []))
                    logger.debug(f"Found {tweet_count} tweets for user: @{username}")
                    
                    for tweet in tweets.get('data', []):
                        tweet_id = tweet.get('id')
                        tweet_text = tweet.get('text', '').lower()
                        
                        # Check for keywords
                        found_keywords = [keyword for keyword in self.target_keywords 
                                         if keyword.lower() in tweet_text]
                        
                        if found_keywords:
                            logger.info(f"Found keywords {found_keywords} in tweet by @{username}")
                            
                            # Store keyword match in database
                            for keyword in found_keywords:
                                keyword_info = {
                                    'Keyword': keyword,
                                    'TweetID': tweet_id,
                                    'UserID': user_id,
                                    'Username': username,
                                    'TweetText': tweet.get('text', ''),
                                    'FoundAt': datetime.now().isoformat()
                                }
                                success = self.db.store_keyword_match(keyword_info)
                                if success:
                                    keyword_matches += 1
                                    keyword_stats[keyword] += 1
                    
                    # Update user's last keyword search time
                    self._update_user_keyword_search_time(user_id)
                    
                    # Apply rate limit-friendly delay between users
                    delay = random.uniform(3, 8)
                    logger.debug(f"Applying delay of {delay:.2f} seconds between users")
                    time.sleep(delay)
                
                except Exception as e:
                    logger.error(f"Error searching keywords for user @{user.get('Username', 'unknown')}: {str(e)}")
                    logger.debug(traceback.format_exc())
                    # Continue with next user rather than stopping completely
            
            # Log detailed stats by keyword
            for keyword, count in keyword_stats.items():
                logger.info(f"Keyword '{keyword}': {count} matches found")
            
            logger.info(f"Total keyword matches found: {keyword_matches}")
            return keyword_matches
            
        except Exception as e:
            logger.error(f"Error in keyword search process: {str(e)}")
            logger.error(traceback.format_exc())
            return keyword_matches
    
    def _get_users_for_keyword_search(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get users for keyword search.
        
        This is a helper method to get users who haven't been checked for keywords recently.
        
        Args:
            limit (int): Maximum number of users to return
            
        Returns:
            List[Dict[str, Any]]: List of user data dictionaries
        """
        # Get recent users with our standard db instance
        try:
            # In production, you'd implement more sophisticated logic to select 
            # which users to check based on when they were last checked
            # For now, we'll just get recent users
            
            # Try to use the db method if it exists
            if hasattr(self.db, 'get_users_for_keyword_search'):
                users = self.db.get_users_for_keyword_search(limit)
                logger.debug(f"Retrieved {len(users)} users for keyword search via db method")
                return users
            
            # Fallback to getting recent users
            recent_days = 30  # Get users from last 30 days
            users = self.db.get_recent_users(days=recent_days)
            
            # Limit the number of users
            return users[:limit]
            
        except Exception as e:
            logger.error(f"Error getting users for keyword search: {str(e)}")
            logger.debug(traceback.format_exc())
            return []
    
    def _update_user_keyword_search_time(self, user_id: str) -> bool:
        """
        Update the last time a user was checked for keywords.
        
        Args:
            user_id (str): User ID to update
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get current user data
            user_data = self.db.get_user_data(user_id)
            if user_data:
                # Update last keyword search time
                user_data['LastKeywordSearch'] = datetime.now().isoformat()
                # Store updated user data
                return self.db.store_user_data(user_data)
            return False
        except Exception as e:
            logger.error(f"Error updating user keyword search time: {str(e)}")
            return False
    
    def engage_with_users(self) -> Dict[str, int]:
        """
        Engage with users by liking, retweeting, and commenting on their tweets.
        
        This method retrieves tweets with keywords that we haven't engaged with yet,
        and then likes, retweets, and comments on those tweets.
        
        Returns:
            Dict[str, int]: Dictionary with counts of different engagement types
        """
        logger.info("Engaging with users")
        engagement_counts = {'likes': 0, 'retweets': 0, 'comments': 0}
        
        try:
            # Get tweets with keywords that we haven't engaged with yet
            tweets = self._get_tweets_for_engagement(limit=10)
            logger.info(f"Retrieved {len(tweets)} tweets for engagement")
            
            if not tweets:
                logger.info("No tweets found for engagement")
                return engagement_counts
            
            for tweet in tweets:
                try:
                    tweet_id = tweet.get('TweetID')
                    user_id = tweet.get('UserID')
                    keyword = tweet.get('Keyword')
                    username = tweet.get('Username')
                    tweet_text = tweet.get('TweetText', '')
                    
                    if not tweet_id or not user_id:
                        logger.warning(f"Missing tweet_id or user_id in tweet data: {tweet}")
                        continue
                    
                    # Like the tweet
                    logger.info(f"Liking tweet {tweet_id} from @{username}")
                    like_result = self.twitter.like_tweet(tweet_id)
                    if like_result:
                        engagement_counts['likes'] += 1
                        logger.info(f"Successfully liked tweet from @{username}")
                        
                        # Update engagement in database
                        self._record_engagement(user_id, 'Like', tweet_id)
                    else:
                        logger.warning(f"Failed to like tweet from @{username}")
                    
                    # Apply random delay
                    delay = random.uniform(5, 15)
                    logger.debug(f"Applying delay of {delay:.2f} seconds before next action")
                    time.sleep(delay)
                    
                    # Retweet
                    logger.info(f"Retweeting tweet {tweet_id} from @{username}")
                    retweet_result = self.twitter.retweet(tweet_id)
                    if retweet_result:
                        engagement_counts['retweets'] += 1
                        logger.info(f"Successfully retweeted tweet from @{username}")
                        
                        # Update engagement in database
                        self._record_engagement(user_id, 'Retweet', tweet_id)
                    else:
                        logger.warning(f"Failed to retweet tweet from @{username}")
                    
                    # Apply random delay
                    delay = random.uniform(8, 20)
                    logger.debug(f"Applying delay of {delay:.2f} seconds before commenting")
                    time.sleep(delay)
                    
                    # Generate comment using AI
                    logger.info(f"Generating comment for tweet from @{username}")
                    comment = self.ai.generate_comment(tweet_text)
                    logger.debug(f"Generated comment: {comment}")
                    
                    # Post comment
                    logger.info(f"Commenting on tweet {tweet_id} from @{username}")
                    comment_result = self.twitter.reply_to_tweet(tweet_id, comment)
                    if comment_result:
                        engagement_counts['comments'] += 1
                        logger.info(f"Successfully commented on tweet from @{username}")
                        
                        # Update engagement in database
                        self._record_engagement(user_id, 'Comment', tweet_id)
                    else:
                        logger.warning(f"Failed to comment on tweet from @{username}")
                    
                    # Mark tweet as engaged
                    self._mark_tweet_as_engaged(tweet_id, keyword)
                    
                    # Apply longer delay between users
                    delay = random.uniform(45, 90)
                    logger.debug(f"Applying delay of {delay:.2f} seconds before next user")
                    time.sleep(delay)
                    
                    logger.info(f"Successfully engaged with tweet from @{username}")
                    
                except Exception as e:
                    logger.error(f"Error engaging with tweet {tweet.get('TweetID', 'unknown')}: {str(e)}")
                    logger.debug(traceback.format_exc())
                    # Continue with next tweet rather than stopping completely
            
            logger.info(f"Engagement summary: {engagement_counts}")
            return engagement_counts
            
        except Exception as e:
            logger.error(f"Error in engagement process: {str(e)}")
            logger.error(traceback.format_exc())
            return engagement_counts
    
    def _get_tweets_for_engagement(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get tweets that match keywords for engagement.
        
        Args:
            limit (int): Maximum number of tweets to return
            
        Returns:
            List[Dict[str, Any]]: List of tweet data dictionaries
        """
        try:
            # Try to use the db method if it exists
            if hasattr(self.db, 'get_tweets_for_engagement'):
                tweets = self.db.get_tweets_for_engagement(limit)
                logger.debug(f"Retrieved {len(tweets)} tweets for engagement via db method")
                return tweets
            
            # If the method doesn't exist, implement a simple version using the keywords table
            # Scan the keywords table for tweets we haven't engaged with yet
            
            # For now, return an empty list and log a warning
            logger.warning("Method get_tweets_for_engagement not available in db")
            return []
            
        except Exception as e:
            logger.error(f"Error getting tweets for engagement: {str(e)}")
            logger.debug(traceback.format_exc())
            return []
    
    def _record_engagement(self, user_id: str, engagement_type: str, tweet_id: str) -> bool:
        """
        Record an engagement with a user in the database.
        
        Args:
            user_id (str): User ID
            engagement_type (str): Type of engagement (Like, Retweet, Comment, DM)
            tweet_id (str): Tweet ID (optional for DMs)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Update engagement stats in database
            engagement_data = {
                'Username': user_id,  # Using user_id as Username for compatibility
                'UserID': user_id,
                'EngagementType': engagement_type,
                'TweetID': tweet_id,
                'Timestamp': datetime.now().isoformat()
            }
            
            # Try to use the db method if it exists
            if hasattr(self.db, 'update_engagement_stats'):
                return self.db.update_engagement_stats(engagement_data)
            
            # Otherwise log a warning
            logger.warning("Method update_engagement_stats not available in db")
            return False
            
        except Exception as e:
            logger.error(f"Error recording engagement: {str(e)}")
            return False
    
    def _mark_tweet_as_engaged(self, tweet_id: str, keyword: str) -> bool:
        """
        Mark a tweet as having been engaged with.
        
        Args:
            tweet_id (str): Tweet ID
            keyword (str): Keyword that matched this tweet
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Try to use the db method if it exists
            if hasattr(self.db, 'mark_tweet_as_engaged'):
                return self.db.mark_tweet_as_engaged(tweet_id)
            
            # If the method doesn't exist, log a warning
            logger.warning("Method mark_tweet_as_engaged not available in db")
            return False
            
        except Exception as e:
            logger.error(f"Error marking tweet as engaged: {str(e)}")
            return False
    
    def post_tweets_with_images(self) -> bool:
        """
        Post tweets with images using AI-generated captions.
        
        This method gets content from the content manager, generates tweet text
        using AI, and posts it to Twitter.
        
        Returns:
            bool: True if posting was successful, False otherwise
        """
        logger.info("Posting tweets with images")
        
        try:
            # Check if we should post now based on rate limits
            max_tweets_per_day = int(os.getenv('MAX_TWEETS_PER_DAY', '3'))
            tweets_posted_today = 0  # In production you'd track this properly
            
            if tweets_posted_today >= max_tweets_per_day:
                logger.info(f"Already posted {tweets_posted_today} tweets today (max: {max_tweets_per_day})")
                return False
            
            # Get content for posting
            content = self.content_manager.get_next_content_for_posting()
            
            if not content:
                logger.info("No content available for posting")
                return False
            
            image_path = content.get('image_path')
            summary = content.get('summary', '')
            folder_name = content.get('folder_name', 'unknown')
            
            logger.info(f"Selected content from folder: {folder_name}")
            logger.info(f"Image path: {image_path}")
            logger.debug(f"Summary: {summary[:100]}...")
            
            # Validate image path
            if not os.path.exists(image_path):
                logger.error(f"Image file not found: {image_path}")
                self.content_manager.mark_content_as_posted(content.get('id'))
                return False
            
            # Generate tweet text using AI
            logger.info("Generating tweet text with AI")
            tweet_text = self.ai.generate_tweet_text(image_path, summary)
            logger.info(f"Generated tweet text: {tweet_text}")
            
            # Post tweet with image
            logger.info(f"Posting tweet with image: {os.path.basename(image_path)}")
            result = self.twitter.post_tweet_with_media(tweet_text, image_path)
            
            if result:
                tweet_id = result.get('data', {}).get('id', 'unknown')
                logger.info(f"Tweet posted successfully! Tweet ID: {tweet_id}")
                
                # Mark content as posted
                self.content_manager.mark_content_as_posted(content.get('id'))
                
                # Save posting history if db method exists
                self._save_posting_history(content.get('id'), tweet_id)
                
                return True
            else:
                logger.error("Failed to post tweet")
                return False
            
        except Exception as e:
            logger.error(f"Error posting tweet with image: {str(e)}")
            logger.error(traceback.format_exc())
            return False
    
    def _save_posting_history(self, content_id: str, tweet_id: str) -> bool:
        """
        Save content posting history to the database.
        
        Args:
            content_id (str): Content ID
            tweet_id (str): Posted tweet ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Create history entry
            history = {
                'content_id': content_id,
                'tweet_id': tweet_id,
                'timestamp': datetime.now().isoformat(),
                'status': 'posted'
            }
            
            # Try to use the db method if it exists
            if hasattr(self.db, 'save_posting_history'):
                return self.db.save_posting_history(history)
            
            # Otherwise just log
            logger.info(f"Posted content {content_id} as tweet {tweet_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving posting history: {str(e)}")
            return False
    
    def engage_with_public_reply(self, user_id: str, username: str, message: str) -> bool:
        """
        Engage with a user through a public reply when DM fails.
        
        This method is used as a fallback when DM sending fails due to permissions.
        It finds a recent tweet from the user and replies to it with a modified version
        of the message that would have been sent as a DM.
        
        Args:
            user_id (str): Twitter user ID
            username (str): Twitter username
            message (str): Message to send (originally intended as DM)
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info(f"Attempting public reply fallback for @{username}")
        
        try:
            # Get user's recent tweets
            tweets = self.twitter.get_user_tweets(user_id, max_results=5)
            
            if 'data' not in tweets or not tweets['data']:
                logger.warning(f"No recent tweets found for @{username}, cannot use public reply fallback")
                return False
            
            # Get the most recent tweet
            tweet = tweets['data'][0]
            tweet_id = tweet['id']
            
            # Modify the message for public context (shorter, less personal)
            # Remove "Hey @username" if it exists since we're replying directly
            public_message = message
            if public_message.startswith(f"Hey @{username}") or public_message.startswith(f"Hi @{username}"):
                public_message = public_message.split("!", 1)[1] if "!" in public_message else public_message
            
            # Make sure it's not too long for a tweet
            if len(public_message) > 260:  # Leave some room for formatting
                public_message = public_message[:257] + "..."
                
            # Format as a reply
            public_message = public_message.strip()
            
            # Post the reply
            logger.info(f"Replying to tweet {tweet_id} from @{username} as DM alternative")
            result = self.twitter.reply_to_tweet(tweet_id, public_message)
            
            if result:
                logger.info(f"Successfully sent public reply to @{username} as DM alternative")
                self._record_engagement(user_id, 'Reply', tweet_id)
                return True
            else:
                logger.error(f"Failed to send public reply to @{username}")
                return False
                
        except Exception as e:
            logger.error(f"Error in public reply fallback for @{username}: {str(e)}")
            logger.debug(traceback.format_exc())
            return False

    def send_dms_to_users(self) -> int:
        """
        Send personalized DMs to relevant users.
        Falls back to public replies when DMs fail due to permissions.
        
        Returns:
            int: Number of successful engagements (DMs or fallback replies)
        """
        logger.info("Sending DMs to users")
        dms_sent = 0
        fallback_replies = 0
        permission_errors = 0
        
        try:
            # Check rate limits
            max_dms_per_day = int(os.getenv('MAX_DMS_PER_DAY', '5'))
            dms_sent_today = 0  # In production you'd track this properly
            
            if dms_sent_today >= max_dms_per_day:
                logger.info(f"Already sent {dms_sent_today} DMs today (max: {max_dms_per_day})")
                return 0
            
            # Get DM context from file
            dm_context = self._get_dm_context()
            
            # Get users who match our criteria and haven't received a DM yet
            users = self._get_users_for_dm(limit=min(5, max_dms_per_day - dms_sent_today))
            logger.info(f"Retrieved {len(users)} users for DM sending")
            
            for user in users:
                try:
                    user_id = user.get('UserID')
                    username = user.get('Username', '')
                    
                    logger.info(f"Preparing DM for user: @{username}")
                    
                    # Generate personalized DM using AI
                    logger.info(f"Generating personalized DM for @{username}")
                    dm_text = self.ai.generate_dm(username, dm_context)
                    logger.debug(f"Generated DM text: {dm_text}")
                    
                    # Send DM
                    logger.info(f"Sending DM to user: @{username}")
                    result = self.twitter.send_dm_to_user(user_id, dm_text)
                    
                    if result:
                        # Update database to mark as DM sent
                        self._record_engagement(user_id, 'DM', '')
                        self._mark_user_dm_sent(user_id)
                        dms_sent += 1
                        logger.info(f"Successfully sent DM to @{username}")
                    else:
                        logger.error(f"Failed to send DM to @{username}")
                        
                        # Try fallback to public reply if DM fails
                        # Only if fallback is enabled in config
                        use_public_fallback = os.getenv('USE_PUBLIC_REPLY_FALLBACK', 'true').lower() in ('true', '1', 'yes')
                        
                        if use_public_fallback:
                            logger.info(f"Attempting public reply fallback for @{username}")
                            reply_success = self.engage_with_public_reply(user_id, username, dm_text)
                            
                            if reply_success:
                                fallback_replies += 1
                                logger.info(f"Successfully engaged with @{username} via public reply fallback")
                                # Still mark as attempted since the DM itself failed
                                self._mark_user_dm_attempted(user_id)
                            else:
                                logger.warning(f"Both DM and public reply fallback failed for @{username}")
                                self._mark_user_dm_attempted(user_id)
                        else:
                            # Just mark as attempted if fallback is disabled
                            self._mark_user_dm_attempted(user_id)
                    
                    # Apply delay between attempts
                    if user != users[-1]:  # Skip delay after last user
                        delay = random.uniform(30, 60)  # Reduced for testing (normally 300-600)
                        logger.info(f"Applying delay of {delay:.2f} seconds before next engagement")
                        time.sleep(delay)
                    
                except Exception as e:
                    logger.error(f"Error sending DM to user @{user.get('Username', 'unknown')}: {str(e)}")
                    
                    # Check for permission errors
                    if "403 Client Error: Forbidden" in str(e):
                        permission_errors += 1
                        logger.warning(f"Permission error for @{user.get('Username', 'unknown')} - user likely doesn't follow your bot or has closed their DMs")
                        
                        # Try fallback to public reply if it's a permission error
                        use_public_fallback = os.getenv('USE_PUBLIC_REPLY_FALLBACK', 'true').lower() in ('true', '1', 'yes')
                        
                        if use_public_fallback:
                            try:
                                # We already generated the DM text earlier
                                fallback_success = self.engage_with_public_reply(
                                    user.get('UserID'), 
                                    user.get('Username', ''),
                                    dm_text
                                )
                                
                                if fallback_success:
                                    fallback_replies += 1
                                    logger.info(f"Successfully engaged with @{user.get('Username', '')} via public reply fallback")
                            except Exception as fallback_error:
                                logger.error(f"Error in public reply fallback: {str(fallback_error)}")
                    
                    # Mark as attempted regardless of errors
                    try:
                        self._mark_user_dm_attempted(user.get('UserID'))
                    except Exception as mark_error:
                        logger.error(f"Error marking user as attempted: {str(mark_error)}")
                    
                    # Continue with next user rather than stopping completely
            
            # Log summary with additional details
            total_engagements = dms_sent + fallback_replies
            logger.info(f"Engagement summary: {dms_sent} DMs sent, {fallback_replies} public replies sent")
            logger.info(f"Total successful engagements: {total_engagements}")
            
            if permission_errors > 0:
                logger.warning(f"DM permission errors: {permission_errors}")
                logger.warning("To send DMs, users must either follow your bot or have their DMs open to everyone")
            
            return total_engagements
            
        except Exception as e:
            logger.error(f"Error in DM sending process: {str(e)}")
            logger.error(traceback.format_exc())
            return dms_sent
    
    def _get_dm_context(self) -> str:
        """
        Get DM context from file or fallback to default.
        
        Returns:
            str: DM context text
        """
        dm_context = ""
        try:
            dm_context_file = os.getenv('DM_CONTEXT_FILE', 'dm_context.txt')
            
            if os.path.exists(dm_context_file):
                with open(dm_context_file, 'r', encoding='utf-8') as f:
                    dm_context = f.read()
                    logger.debug(f"Loaded DM context from {dm_context_file}")
            else:
                logger.warning(f"DM context file {dm_context_file} not found")
                dm_context = """
                Our Kickstarter campaign features exclusive comic book art created by talented artists.
                We offer limited edition prints, digital downloads, and more.
                Check out our campaign page for more details and early bird rewards!
                """
                logger.debug("Using default DM context")
        except Exception as e:
            logger.error(f"Error reading DM context file: {str(e)}")
            logger.info("Using default DM context")
            dm_context = "Thank you for your interest in comic art and Kickstarter campaigns."
        
        return dm_context
    
    def add_test_user_for_dm(self):
        """
        Add a test user to the database for DM testing.
        
        This method manually adds a test user to the database
        with appropriate flags set for DM targeting.
        
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info("Adding test user for DM functionality")
        
        try:
            # Use already stored users if available
            stored_users = self.db.get_recent_users(days=30)
            if stored_users:
                # Pick the first user
                test_user = stored_users[0]
                user_id = test_user.get('UserID')
                username = test_user.get('Username', 'unknown')
                
                logger.info(f"Using existing user @{username} for DM test")
                
                # Update the user record to enable DM targeting
                test_user['DMSent'] = False
                test_user['KeywordMatch'] = True
                test_user['EngagementScore'] = 3  # Arbitrary score
                
                # Store the updated user
                success = self.db.store_user_data(test_user)
                if success:
                    logger.info(f"Successfully updated user @{username} for DM testing")
                    return True
                else:
                    logger.warning(f"Failed to update user @{username}")
                    return False
            
            # If no stored users, create a test user (use your own test account ID)
            test_user = {
                'UserID': '1887169625462595584',  # Replace with your own test account ID
                'Username': 'your_test_account',  # Replace with your username
                'FollowerCount': 100,
                'ProfileAge': 365,
                'TweetCount': 500,
                'HashtagsUsed': ['Kickstarter'],
                'KeywordMatch': True,
                'DMSent': False,
                'LastEngagementDate': datetime.now().isoformat(),
                'EngagementScore': 3
            }
            
            success = self.db.store_user_data(test_user)
            if success:
                logger.info(f"Successfully added test user @{test_user['Username']} for DM testing")
                return True
            else:
                logger.warning(f"Failed to add test user @{test_user['Username']}")
                return False
            
        except Exception as e:
            logger.error(f"Error adding test user for DM: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def _get_users_for_dm(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get users who meet criteria for receiving DMs.
        
        This method attempts multiple fallback strategies to find eligible users,
        even if there are no perfectly matching users in the database.
        
        Args:
            limit (int): Maximum number of users to return
        
        Returns:
            List[Dict[str, Any]]: List of user data dictionaries
        """
        logger.info("Finding users for DM sending")
        
        try:
            # STRATEGY 1: Try the standard db method
            if hasattr(self.db, 'get_users_for_dm'):
                users = self.db.get_users_for_dm(limit)
                if users:
                    logger.info(f"Found {len(users)} users via standard DB query")
                    return users
                logger.info("No users found via standard DB query, trying alternatives")
            
            # STRATEGY 2: Get any users from engagement database
            recent_users = []
            if hasattr(self.db, 'get_recent_users'):
                recent_users = self.db.get_recent_users(days=30)
                logger.info(f"Found {len(recent_users)} recent users in database")
            
            # If we have recent users, check if any are eligible for DMs
            eligible_users = []
            for user in recent_users:
                # If user has already been sent a DM, skip unless override is enabled
                if user.get('DMSent', False):
                    continue
                    
                # Add this user to eligible list
                eligible_users.append(user)
                logger.info(f"Found eligible user for DM: @{user.get('Username', 'unknown')}")
            
            if eligible_users:
                # Sort by engagement score if available, or follower count
                eligible_users.sort(
                    key=lambda u: (u.get('EngagementScore', 0), u.get('FollowerCount', 0)), 
                    reverse=True
                )
                # Return limited result set
                result = eligible_users[:limit]
                logger.info(f"Found {len(result)} eligible users for DMs")
                return result
                
            # STRATEGY 3: If no eligible users, convert any hashtag/keyword matched users
            logger.info("No eligible users found, trying to convert engaged users")
            converted_users = []
            for user in recent_users:
                # Make this user eligible for DM by setting DMSent to False
                user_copy = user.copy()  # Create a copy to avoid modifying original
                user_copy['DMSent'] = False
                converted_users.append(user_copy)
                logger.info(f"Converting user @{user.get('Username', 'unknown')} to be eligible for DMs")
                # Only convert up to the limit
                if len(converted_users) >= limit:
                    break
                    
            if converted_users:
                logger.info(f"Converted {len(converted_users)} users to be eligible for DMs")
                return converted_users
                
            # STRATEGY 4: Last resort - create a test user if we're in testing mode
            test_mode = os.getenv('TWITTER_BOT_TEST_MODE', '').lower() in ('true', '1', 'yes')
            if test_mode and os.getenv('TWITTER_USER_ID'):
                logger.info("Creating test user for DM testing (test mode enabled)")
                test_user = {
                    'UserID': os.getenv('TWITTER_USER_ID'),
                    'Username': os.getenv('TWITTER_USERNAME', 'test_user'),
                    'FollowerCount': 100,
                    'ProfileAge': 365,
                    'TweetCount': 500,
                    'HashtagsUsed': ['Kickstarter'],
                    'KeywordMatch': True,
                    'DMSent': False,
                    'LastEngagementDate': datetime.now().isoformat(),
                    'EngagementScore': 3
                }
                logger.info(f"Created test user: @{test_user['Username']}")
                return [test_user]
                
            # If all strategies fail, return empty list
            logger.warning("No users found for DM sending after trying all strategies")
            return []
            
        except Exception as e:
            logger.error(f"Error getting users for DM: {str(e)}")
            logger.debug(traceback.format_exc())
            return []
    
    def _mark_user_dm_sent(self, user_id: str) -> bool:
        """
        Mark a user as having been sent a DM.
        
        Args:
            user_id (str): User ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Try to use the db method if it exists
            if hasattr(self.db, 'mark_user_dm_sent'):
                return self.db.mark_user_dm_sent(user_id)
            
            # Otherwise update the user record
            user_data = self.db.get_user_data(user_id)
            if user_data:
                user_data['DMSent'] = True
                user_data['DMSentAt'] = datetime.now().isoformat()
                return self.db.store_user_data(user_data)
            
            return False
            
        except Exception as e:
            logger.error(f"Error marking user DM sent: {str(e)}")
            return False
        
    def _mark_user_dm_attempted(self, user_id: str) -> bool:
        """
        Mark a user as having had a DM attempt (even if it failed).
        
        Args:
            user_id (str): User ID
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Try to use the db method if it exists
            if hasattr(self.db, 'mark_user_dm_attempted'):
                return self.db.mark_user_dm_attempted(user_id)
            
            # Otherwise update the user record
            user_data = self.db.get_user_data(user_id)
            if user_data:
                user_data['DMAttempted'] = True
                user_data['DMAttemptedAt'] = datetime.now().isoformat()
                return self.db.store_user_data(user_data)
            
            return False
        
        except Exception as e:
            logger.error(f"Error marking user DM attempted: {str(e)}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the Twitter bot.
        
        This method collects status information about various components and
        returns a comprehensive status report.
        
        Returns:
            Dict[str, Any]: Status information dictionary
        """
        try:
            logger.info("Getting bot status")
            
            # Get Twitter API status
            twitter_status = {}
            if hasattr(self.twitter, 'get_status'):
                twitter_status = self.twitter.get_status()
            else:
                twitter_status = {
                    'initialized': self.twitter is not None,
                    'token_valid': self.twitter.token_expiry > time.time() if hasattr(self.twitter, 'token_expiry') else False,
                    'token_expiry': datetime.fromtimestamp(self.twitter.token_expiry).isoformat() if hasattr(self.twitter, 'token_expiry') else 'Unknown'
                }
            
            # Get content manager status
            content_status = {}
            if hasattr(self.content_manager, 'get_status'):
                content_status = self.content_manager.get_status()
            else:
                content_status = {
                    'initialized': self.content_manager is not None,
                    'has_content': bool(self.content_manager.get_next_content_for_posting()) if self.content_manager else False
                }
            
            # Get AI status
            ai_status = {}
            if hasattr(self.ai, 'get_status'):
                ai_status = self.ai.get_status()
            else:
                ai_status = {
                    'initialized': self.ai is not None
                }
            
            # DB status
            db_status = {
                'initialized': self.db is not None
            }
            
            # Last execution times
            execution_times = {}
            for action, time_value in self.last_execution.items():
                if time_value > datetime.min:
                    execution_times[action] = time_value.isoformat()
                else:
                    execution_times[action] = "Never executed"
            
            status = {
                'timestamp': datetime.now().isoformat(),
                'twitter_api': twitter_status,
                'content_manager': content_status,
                'ai': ai_status,
                'db': db_status,
                'last_execution': execution_times,
                'configuration': {
                    'target_hashtags': self.target_hashtags,
                    'target_keywords': self.target_keywords,
                    'min_followers': self.min_followers,
                    'min_profile_age_days': self.min_profile_age_days,
                    'min_tweet_count': self.min_tweet_count,
                    'max_engagement_age_days': self.max_engagement_age_days
                }
            }
            
            logger.info("Status report generated successfully")
            return status
            
        except Exception as e:
            logger.error(f"Error getting status: {str(e)}")
            logger.debug(traceback.format_exc())
            return {
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

# Run the bot if the script is executed directly
if __name__ == "__main__":
    try:
        print(f"Starting Twitter Bot at {datetime.now().isoformat()}")
        bot = TwitterBot()
        
        # Parse command-line arguments
        if len(sys.argv) > 1:
            command = sys.argv[1].lower()
            
            if command == "status":
                # Print status information
                status = bot.get_status()
                print(json.dumps(status, indent=2))
                print(f"Status check completed at {datetime.now().isoformat()}")
            elif command == "find-users":
                # Run just the user finding functionality
                print("Finding and storing users...")
                users_found = bot.find_and_store_users()
                print(f"Done! Found and stored {users_found} users.")
            elif command == "search-keywords":
                # Run just the keyword search functionality
                print("Searching for keywords in tweets...")
                keywords_found = bot.search_keywords_in_tweets()
                print(f"Done! Found {keywords_found} keyword matches.")
            elif command == "engage":
                # Run just the engagement functionality
                print("Engaging with users...")
                engagement = bot.engage_with_users()
                print(f"Done! Engagement summary: {json.dumps(engagement)}")
            elif command == "post":
                # Run just the content posting functionality
                print("Posting tweet with image...")
                success = bot.post_tweets_with_images()
                print(f"Done! {'Tweet posted successfully.' if success else 'Failed to post tweet.'}")
            elif command == "dm":
                # Run just the DM sending functionality
                print("Sending DMs to users...")
                dms_sent = bot.send_dms_to_users()
                print(f"Done! Sent {dms_sent} DMs.")
            else:
                print(f"Unknown command: {command}")
                print("Available commands: status, find-users, search-keywords, engage, post, dm")
        else:
            # Run the complete workflow
            print("Running complete bot workflow...")
            success = bot.run()
            print(f"Bot execution {'succeeded' if success else 'failed'}.")
        
        print(f"Twitter Bot finished at {datetime.now().isoformat()}")
        
    except Exception as e:
        print(f"Critical error: {str(e)}")
        logger.critical(f"Unhandled exception in main: {str(e)}")
        logger.critical(traceback.format_exc())
        sys.exit(1)