"""
Twitter API Interactions for Twitter Bot

This module handles all interactions with the Twitter API, including both OAuth 2.0 
authorization flow and API interactions using v1.1 and v2 endpoints.

Key features:
- OAuth 2.0 token management with automatic refresh
- Rate limit handling with exponential backoff
- Comprehensive error handling for all API calls
- Support for both v1.1 and v2 Twitter API endpoints
"""

import os
import time
import json
import secrets
import hashlib
import base64
import random
import logging
import threading
from urllib.parse import urlencode
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union, Tuple

import requests
from requests_oauthlib import OAuth1
from flask import Flask, request, redirect, jsonify, session
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.getenv('MAIN_LOG_FILE', 'main.log')),
            logging.StreamHandler()
        ]
    )

# Twitter API v1.1 credentials
TWITTER_API_KEY = os.getenv("TWITTER_CONSUMER_KEY", os.getenv("TWITTER_API_KEY"))
TWITTER_API_SECRET = os.getenv("TWITTER_CONSUMER_SECRET", os.getenv("TWITTER_API_SECRET"))
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET", os.getenv("TWITTER_ACCESS_SECRET"))
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# Twitter OAuth 2.0 credentials
CLIENT_ID = os.getenv("OAUTH_2_CLIENT_ID", os.getenv("TWITTER_CLIENT_ID"))
CLIENT_SECRET = os.getenv("OAUTH_2_CLIENT_SECRET", os.getenv("TWITTER_CLIENT_SECRET"))
OAUTH2_ACCESS_TOKEN = os.getenv("OAUTH_2_ACCESS_TOKEN", os.getenv("TWITTER_OAUTH2_ACCESS_TOKEN"))
OAUTH2_REFRESH_TOKEN = os.getenv("OAUTH_2_REFRESH_TOKEN", os.getenv("TWITTER_OAUTH2_REFRESH_TOKEN"))
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://127.0.0.1:5000/callback")
USER_ID = os.getenv("USER_ID", os.getenv("TWITTER_USER_ID"))

# Get token expiry with error handling
try:
    TOKEN_EXPIRY = float(os.getenv("TWITTER_TOKEN_EXPIRY", os.getenv("TOKEN_EXPIRY", "0")))
except (ValueError, TypeError):
    logger.warning("Invalid token expiry value, defaulting to 0")
    TOKEN_EXPIRY = 0

# Log credential availability for debugging
logger.debug(f"API Key available: {bool(TWITTER_API_KEY)}")
logger.debug(f"Bearer Token available: {bool(TWITTER_BEARER_TOKEN)}")
logger.debug(f"OAuth2 Access Token available: {bool(OAUTH2_ACCESS_TOKEN)}")
logger.debug(f"User ID configured: {USER_ID}")
logger.debug(f"Token expiry: {datetime.fromtimestamp(TOKEN_EXPIRY).isoformat() if TOKEN_EXPIRY > 0 else 'Not set'}")

# Scopes required for the bot
SCOPES = "tweet.read tweet.write users.read offline.access"

# Twitter API endpoints
AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
API_V1_BASE = "https://api.twitter.com/1.1"
API_V2_BASE = "https://api.twitter.com/2"
UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"

# Rate limiting configuration - Using environment variables with defaults
MAX_LIKES_PER_HOUR = int(os.getenv("MAX_LIKES_PER_HOUR", "15"))
MAX_RETWEETS_PER_HOUR = int(os.getenv("MAX_RETWEETS_PER_HOUR", "8"))
MAX_COMMENTS_PER_HOUR = int(os.getenv("MAX_COMMENTS_PER_HOUR", "5"))
MAX_DMS_PER_HOUR = int(os.getenv("MAX_DMS_PER_HOUR", "2"))
MAX_TWEETS_PER_HOUR = int(os.getenv("MAX_TWEETS_PER_HOUR", "1"))
MAX_TWEETS_WITH_MEDIA_PER_HOUR = int(os.getenv("MAX_TWEETS_WITH_MEDIA_PER_HOUR", "1"))

# Delay settings (in seconds) - Using environment variables with defaults
MIN_DELAY_BETWEEN_LIKES = int(os.getenv("MIN_DELAY_BETWEEN_LIKES", "120"))
MAX_DELAY_BETWEEN_LIKES = int(os.getenv("MAX_DELAY_BETWEEN_LIKES", "300"))
MIN_DELAY_BETWEEN_COMMENTS = int(os.getenv("MIN_DELAY_BETWEEN_COMMENTS", "300"))
MAX_DELAY_BETWEEN_COMMENTS = int(os.getenv("MAX_DELAY_BETWEEN_COMMENTS", "900"))
MIN_DELAY_BETWEEN_TWEETS = int(os.getenv("MIN_DELAY_BETWEEN_TWEETS", "3600"))
MAX_DELAY_BETWEEN_TWEETS = int(os.getenv("MAX_DELAY_BETWEEN_TWEETS", "7200"))
MIN_DELAY_BETWEEN_DMS = int(os.getenv("MIN_DELAY_BETWEEN_DMS", "1800"))
MAX_DELAY_BETWEEN_DMS = int(os.getenv("MAX_DELAY_BETWEEN_DMS", "3600"))

# Log rate limit configuration
logger.info(f"Rate limits configured - Likes: {MAX_LIKES_PER_HOUR}/hr, Retweets: {MAX_RETWEETS_PER_HOUR}/hr, Comments: {MAX_COMMENTS_PER_HOUR}/hr")
logger.info(f"Delay settings - Likes: {MIN_DELAY_BETWEEN_LIKES}-{MAX_DELAY_BETWEEN_LIKES}s, Comments: {MIN_DELAY_BETWEEN_COMMENTS}-{MAX_DELAY_BETWEEN_COMMENTS}s")

# OAuth 2.0 Flask app for authorization
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

# Keep track of token refresh operations
token_refresh_lock = threading.Lock()
last_token_refresh_attempt = 0
token_refresh_cooldown = 60  # Wait 60 seconds between refresh attempts


class TwitterAPI:
    """
    Twitter API interaction handler for both v1.1 and v2 endpoints.
    
    This class handles all interactions with the Twitter API, including OAuth 2.0
    token management, rate limiting, error handling, and API calls.
    
    Attributes:
        oauth1: OAuth1 authentication for v1.1 API endpoints
        oauth2_token: Current OAuth 2.0 access token
        oauth2_refresh_token: Current OAuth 2.0 refresh token
        token_expiry: Timestamp when the current token expires
        user_id: Twitter user ID for authenticated user
        rate_limits: Dictionary tracking rate limits for different API actions
    """
    
    def __init__(self):
        """
        Initialize the TwitterAPI with current tokens and authentication.
        """
        logger.info("Initializing TwitterAPI...")
        
        # Check credentials and log warnings if missing
        self._check_credentials()
        
        # Initialize OAuth 1.0a for v1.1 API
        self.oauth1 = OAuth1(
            TWITTER_API_KEY,
            client_secret=TWITTER_API_SECRET,
            resource_owner_key=TWITTER_ACCESS_TOKEN,
            resource_owner_secret=TWITTER_ACCESS_SECRET
        )
        
        # Current OAuth 2.0 tokens
        self.oauth2_token = OAUTH2_ACCESS_TOKEN
        self.oauth2_refresh_token = OAUTH2_REFRESH_TOKEN
        try:
            # Try to get from immediate environment first (may be more updated than TOKEN_EXPIRY global)
            self.token_expiry = float(os.getenv("TWITTER_TOKEN_EXPIRY", os.getenv("TOKEN_EXPIRY", str(TOKEN_EXPIRY))))
        except (ValueError, TypeError):
            self.token_expiry = TOKEN_EXPIRY
            logger.warning(f"Using fallback token expiry: {self.token_expiry}")
        
        # Store rate limit data
        self.rate_limits = {
            'likes': {'count': 0, 'reset_time': time.time() + 3600},
            'retweets': {'count': 0, 'reset_time': time.time() + 3600},
            'comments': {'count': 0, 'reset_time': time.time() + 3600},
            'dms': {'count': 0, 'reset_time': time.time() + 3600},
            'tweets': {'count': 0, 'reset_time': time.time() + 3600},
            'tweets_with_media': {'count': 0, 'reset_time': time.time() + 3600},
        }
        
        # User ID for OAuth 2.0 endpoints that need it
        self.user_id = USER_ID
        
        # Init time for diagnostics
        self.init_time = time.time()
        
        # Validate token status immediately
        token_status = "valid" if self.token_expiry > time.time() else "expired"
        expiry_str = datetime.fromtimestamp(self.token_expiry).strftime('%Y-%m-%d %H:%M:%S') if self.token_expiry > 0 else "Not set"
        logger.info(f"OAuth2 token status: {token_status}, expires: {expiry_str}")
        
        # Verify token on init if enabled
        if os.getenv("VERIFY_TOKEN_ON_INIT", "false").lower() in ("true", "1", "yes"):
            logger.info("Verifying token on initialization...")
            self.refresh_oauth2_token_if_needed()
        
        logger.info("TwitterAPI initialized successfully")
    
    def _check_credentials(self) -> None:
        """
        Check if all required credentials are available and log warnings if not.
        """
        # Check Twitter API v1.1 credentials
        if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
            missing = []
            if not TWITTER_API_KEY: missing.append("TWITTER_API_KEY")
            if not TWITTER_API_SECRET: missing.append("TWITTER_API_SECRET")
            if not TWITTER_ACCESS_TOKEN: missing.append("TWITTER_ACCESS_TOKEN") 
            if not TWITTER_ACCESS_SECRET: missing.append("TWITTER_ACCESS_SECRET")
            
            logger.warning(f"Missing Twitter API v1.1 credentials: {', '.join(missing)}")
        else:
            logger.info("Twitter API v1.1 credentials validated")
        
        # Check Twitter Bearer Token
        if not TWITTER_BEARER_TOKEN:
            logger.warning("Missing Twitter Bearer Token")
        else:
            logger.info("Twitter Bearer Token validated")
        
        # Check Twitter OAuth 2.0 credentials
        if not all([CLIENT_ID, CLIENT_SECRET]):
            missing = []
            if not CLIENT_ID: missing.append("CLIENT_ID") 
            if not CLIENT_SECRET: missing.append("CLIENT_SECRET")
            
            logger.warning(f"Missing Twitter OAuth 2.0 app credentials: {', '.join(missing)}")
        else:
            logger.info("Twitter OAuth 2.0 app credentials validated")
        
        # Check OAuth 2.0 tokens
        if not all([OAUTH2_ACCESS_TOKEN, OAUTH2_REFRESH_TOKEN]):
            missing = []
            if not OAUTH2_ACCESS_TOKEN: missing.append("OAUTH2_ACCESS_TOKEN")
            if not OAUTH2_REFRESH_TOKEN: missing.append("OAUTH2_REFRESH_TOKEN")
            
            logger.warning(f"Missing Twitter OAuth 2.0 tokens: {', '.join(missing)}")
        else:
            logger.info("Twitter OAuth 2.0 tokens validated")
            
        # Check User ID
        if not USER_ID:
            logger.warning("Missing Twitter User ID. Some functionality may not work.")
        else:
            logger.info(f"Twitter User ID validated: {USER_ID}")
    
    def refresh_oauth2_token_if_needed(self) -> bool:
        """
        Check if the OAuth 2.0 token is expired and refresh it if needed.
        
        Returns:
            bool: True if token is valid or was refreshed successfully, False otherwise
        """
        global last_token_refresh_attempt
        
        current_time = time.time()
        
        # Token is considered expired if it's within 5 minutes of expiry
        if self.token_expiry - current_time < 300:
            time_to_expiry = self.token_expiry - current_time
            if time_to_expiry <= 0:
                logger.info(f"OAuth 2.0 token is expired by {abs(time_to_expiry):.1f} seconds")
            else:
                logger.info(f"OAuth 2.0 token expires in {time_to_expiry:.1f} seconds (refresh needed)")
            
            # Check if we've attempted a refresh recently to avoid repeated failures
            with token_refresh_lock:
                cooldown_remaining = token_refresh_cooldown - (current_time - last_token_refresh_attempt)
                if current_time - last_token_refresh_attempt < token_refresh_cooldown:
                    logger.info(f"Skipping token refresh - attempted recently. Will try again in {cooldown_remaining:.1f} seconds")
                    return False
                
                # Update the last attempt time
                last_token_refresh_attempt = current_time
                logger.debug(f"Setting last token refresh attempt to {current_time}")
            
            # Try to refresh the token
            refresh_result = self.refresh_oauth2_token()
            logger.info(f"Token refresh attempt result: {'SUCCESS' if refresh_result else 'FAILED'}")
            return refresh_result
        else:
            time_to_expiry = self.token_expiry - current_time
            logger.debug(f"OAuth 2.0 token is valid for {time_to_expiry:.1f} more seconds")
            return True
    
    def refresh_oauth2_token(self) -> bool:
        """
        Refresh the OAuth 2.0 token using the refresh token.
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.oauth2_refresh_token:
            logger.error("No refresh token available. Cannot refresh OAuth 2.0 token.")
            return False
        
        # Mark first/last characters of token for logging
        if self.oauth2_refresh_token and len(self.oauth2_refresh_token) > 10:
            token_preview = f"{self.oauth2_refresh_token[:5]}...{self.oauth2_refresh_token[-5:]}"
            logger.debug(f"Using refresh token: {token_preview}")
        else:
            logger.warning("Refresh token appears invalid or too short")
            
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.oauth2_refresh_token
        }
        
        auth_tuple = (CLIENT_ID, CLIENT_SECRET)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            logger.info("Refreshing OAuth 2.0 token...")
            start_time = time.time()
            response = requests.post(TOKEN_URL, data=data, headers=headers, auth=auth_tuple, timeout=30)
            elapsed = time.time() - start_time
            
            if response.status_code == 400:
                # Try to extract error information
                try:
                    error_data = response.json()
                    error_message = error_data.get('error_description', error_data.get('error', 'Unknown error'))
                    logger.error(f"Failed to refresh OAuth 2.0 token: {error_message}")
                except:
                    logger.error(f"Failed to refresh OAuth 2.0 token: HTTP 400 Bad Request")
                return False
                
            response.raise_for_status()
            
            token_data = response.json()
            self.oauth2_token = token_data.get('access_token')
            
            # Some token responses include a new refresh token
            if 'refresh_token' in token_data:
                logger.info("Received new refresh token with response")
                self.oauth2_refresh_token = token_data.get('refresh_token')
            
            # Set expiry time (default to 2 hours if not provided)
            expires_in = token_data.get('expires_in', 7200)
            self.token_expiry = time.time() + expires_in
            
            # Update environment variables for persistence
            os.environ["OAUTH_2_ACCESS_TOKEN"] = self.oauth2_token
            os.environ["TOKEN_EXPIRY"] = str(self.token_expiry)
            os.environ["TWITTER_TOKEN_EXPIRY"] = str(self.token_expiry)
            if 'refresh_token' in token_data:
                os.environ["OAUTH_2_REFRESH_TOKEN"] = self.oauth2_refresh_token
            
            # Try to update .env file 
            try:
                env_update_result = self._update_env_file({
                    'OAUTH_2_ACCESS_TOKEN': self.oauth2_token,
                    'TOKEN_EXPIRY': str(self.token_expiry),
                    'OAUTH_2_REFRESH_TOKEN': self.oauth2_refresh_token if 'refresh_token' in token_data else None
                })
                if env_update_result:
                    logger.info("Successfully updated .env file with new tokens")
                else:
                    logger.warning("Failed to update .env file with new tokens")
            except Exception as e:
                logger.warning(f"Could not update .env file with new tokens: {str(e)}")
            
            expiry_datetime = datetime.fromtimestamp(self.token_expiry).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"Successfully refreshed OAuth 2.0 token in {elapsed:.2f}s. New expiry: {expiry_datetime}")
            
            # Log token preview for debugging
            if self.oauth2_token and len(self.oauth2_token) > 10:
                token_preview = f"{self.oauth2_token[:5]}...{self.oauth2_token[-5:]}"
                logger.debug(f"New token: {token_preview}")
                
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error refreshing OAuth 2.0 token: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error refreshing OAuth 2.0 token: {str(e)}")
            return False
        
    def reload_tokens_from_env(self):
        """
        Reload OAuth 2.0 tokens directly from environment variables.
        
        Returns:
            bool: True if tokens were successfully loaded, False otherwise
        """
        try:
            # Load from environment variables
            new_token = os.getenv('OAUTH_2_ACCESS_TOKEN')
            expiry_str = os.getenv('TWITTER_TOKEN_EXPIRY', os.getenv('TOKEN_EXPIRY', '0'))
            
            if not new_token:
                logger.error("No OAuth 2.0 token found in environment variables")
                return False
            
            try:
                new_expiry = float(expiry_str)
            except (ValueError, TypeError):
                logger.warning(f"Invalid expiry value: {expiry_str}, using default")
                new_expiry = time.time() + (7 * 24 * 60 * 60)  # 7 days default
            
            # Update token values
            old_token = "None"
            if self.oauth2_token:
                old_token = f"{self.oauth2_token[:5]}...{self.oauth2_token[-5:]}"
            
            self.oauth2_token = new_token
            self.token_expiry = new_expiry
            
            # Log the change
            new_token_preview = f"{new_token[:5]}...{new_token[-5:]}"
            expiry_time = datetime.fromtimestamp(new_expiry).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"Tokens reloaded from environment: {old_token} → {new_token_preview}")
            logger.info(f"New token expires at: {expiry_time}")
            
            return True
        except Exception as e:
            logger.error(f"Error reloading tokens from environment: {str(e)}")
            return False
        
    def update_token_directly(self, new_token=None, new_expiry=None):
        """
        Directly update the OAuth 2.0 token without reading from environment.
        
        Args:
            new_token (str, optional): New OAuth 2.0 token to use
            new_expiry (float, optional): New token expiry timestamp
        
        Returns:
            bool: True if token was updated, False otherwise
        """
        try:
            # If no token is provided, try to read from environment
            if new_token is None:
                new_token = os.getenv('OAUTH_2_ACCESS_TOKEN')
                if not new_token:
                    logger.error("No token provided and none found in environment")
                    return False
            
            # If no expiry is provided, try to read from environment
            if new_expiry is None:
                expiry_str = os.getenv('TWITTER_TOKEN_EXPIRY', os.getenv('TOKEN_EXPIRY'))
                if expiry_str:
                    try:
                        new_expiry = float(expiry_str)
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid token expiry value: {expiry_str}")
                        # Default to 7 days
                        new_expiry = time.time() + (7 * 24 * 60 * 60)
                else:
                    # Default to 7 days
                    new_expiry = time.time() + (7 * 24 * 60 * 60)
            
            # Update token and expiry directly
            old_token = None
            if self.oauth2_token:
                old_token = f"{self.oauth2_token[:5]}...{self.oauth2_token[-5:]}"
            
            self.oauth2_token = new_token
            self.token_expiry = new_expiry
            
            new_token_preview = f"{new_token[:5]}...{new_token[-5:]}"
            expiry_time = datetime.fromtimestamp(new_expiry).strftime('%Y-%m-%d %H:%M:%S')
            
            logger.info(f"Token directly updated from {old_token} to {new_token_preview}")
            logger.info(f"New token expires at: {expiry_time}")
            
            return True
        except Exception as e:
            logger.error(f"Error updating token directly: {str(e)}")
            return False
    
    def _update_env_file(self, updates: Dict[str, Optional[str]]) -> bool:
        """
        Update the .env file with new values.
        
        Args:
            updates: Dictionary of environment variables to update
            
        Returns:
            bool: True if successful, False otherwise
        """
        env_path = '.env'
        
        # Skip if file doesn't exist
        if not os.path.exists(env_path):
            logger.warning(f".env file not found at {env_path}")
            return False
        
        try:
            # Read the current .env file
            with open(env_path, 'r') as f:
                lines = f.readlines()
            
            # Track which variables we've updated
            updated_vars = {key: False for key in updates.keys()}
            
            # Update existing variables
            for i, line in enumerate(lines):
                line = line.strip()
                
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                
                # Check if this line matches a variable we want to update
                for var_name, new_value in updates.items():
                    if new_value is None:
                        continue
                        
                    if line.startswith(f"{var_name}="):
                        lines[i] = f"{var_name}={new_value}\n"
                        updated_vars[var_name] = True
                        logger.debug(f"Updated {var_name} in .env file")
            
            # Add any variables that weren't already in the file
            for var_name, updated in updated_vars.items():
                if not updated and updates[var_name] is not None:
                    lines.append(f"{var_name}={updates[var_name]}\n")
                    logger.debug(f"Added new key {var_name} to .env file")
            
            # Write the updated file
            with open(env_path, 'w') as f:
                f.writelines(lines)
            
            logger.info(f"Updated .env file with {sum(1 for u in updated_vars.values() if u)} variables")
            return True
            
        except Exception as e:
            logger.error(f"Error updating .env file: {str(e)}")
            return False
    
    def get_oauth2_headers(self) -> Dict[str, str]:
        """
        Get the authorization headers for OAuth 2.0 requests.
        
        Returns:
            Dict[str, str]: Dictionary of headers for API requests
        """
        # No need to refresh here - we'll handle that separately
        if not self.oauth2_token:
            logger.error("No OAuth 2.0 token available")
            # Try to get from environment as last resort
            self.oauth2_token = os.getenv('OAUTH_2_ACCESS_TOKEN')
            if not self.oauth2_token:
                logger.error("OAuth 2.0 token not found in environment")
                return {"Authorization": "Bearer missing-token", "Content-Type": "application/json"}
        
        # Log token preview for debugging
        token_preview = f"{self.oauth2_token[:5]}...{self.oauth2_token[-5:]}" if len(self.oauth2_token) > 10 else "invalid-token"
        logger.debug(f"Using OAuth 2.0 token: {token_preview}")
        
        headers = {
            "Authorization": f"Bearer {self.oauth2_token}",
            "Content-Type": "application/json"
        }
        return headers
    
    def get_bearer_headers(self) -> Dict[str, str]:
        """
        Get the authorization headers using the app bearer token.
        
        Returns:
            Dict[str, str]: Dictionary of headers for API requests
        """
        if not TWITTER_BEARER_TOKEN:
            logger.warning("Missing TWITTER_BEARER_TOKEN, authentication will likely fail")
            
        headers = {
            "Authorization": f"Bearer {TWITTER_BEARER_TOKEN}",
            "Content-Type": "application/json"
        }
        logger.debug("Generated bearer token request headers")
        return headers
    
    def random_delay(self, min_seconds: int, max_seconds: int) -> None:
        """
        Apply a random delay between actions to avoid rate limiting.
        
        Args:
            min_seconds: Minimum delay in seconds
            max_seconds: Maximum delay in seconds
        """
        delay = random.uniform(min_seconds, max_seconds)
        logger.info(f"Applying random delay of {delay:.2f} seconds")
        time.sleep(delay)
    
    def check_rate_limit(self, action_type: str, max_per_hour: int) -> bool:
        """
        Check if we've hit the rate limit for a specific action.
        
        Args:
            action_type: Type of action (likes, retweets, etc.)
            max_per_hour: Maximum number of actions per hour
            
        Returns:
            bool: True if we can proceed, False if we've hit the limit
        """
        current_time = time.time()
        
        # Reset counter if the hour has passed
        if current_time > self.rate_limits[action_type]['reset_time']:
            logger.info(f"Resetting rate limit counter for {action_type}")
            self.rate_limits[action_type] = {
                'count': 0,
                'reset_time': current_time + 3600
            }
        
        # Check if we've hit the limit
        if self.rate_limits[action_type]['count'] >= max_per_hour:
            reset_time_str = datetime.fromtimestamp(self.rate_limits[action_type]['reset_time']).strftime('%H:%M:%S')
            logger.warning(f"Rate limit reached for {action_type} ({max_per_hour}/hour). Resets at {reset_time_str}")
            return False
        
        # Increment counter and proceed
        self.rate_limits[action_type]['count'] += 1
        logger.debug(f"{action_type} rate limit: {self.rate_limits[action_type]['count']}/{max_per_hour} this hour")
        return True
    
    def wait_for_rate_limit(self, action_type: str, max_per_hour: int) -> None:
        """
        Wait until we can proceed with an action without hitting rate limits.
        
        Args:
            action_type: Type of action (likes, retweets, etc.)
            max_per_hour: Maximum number of actions per hour
        """
        attempt = 0
        while not self.check_rate_limit(action_type, max_per_hour):
            attempt += 1
            wait_time = min(300 * attempt, 1800)  # Exponential backoff, max 30 minutes
            reset_time_str = datetime.fromtimestamp(self.rate_limits[action_type]['reset_time']).strftime('%H:%M:%S')
            logger.info(f"Rate limit for {action_type} reached. Waiting {wait_time} seconds... (attempt {attempt}). Reset at {reset_time_str}")
            time.sleep(wait_time)
        
        logger.info(f"Rate limit check passed for {action_type}")
    
    #-----------------
    # User Search APIs
    #-----------------
    
    def search_recent_tweets(self, hashtag: str, max_results: int = 100) -> Dict[str, Any]:
        """
        Search for recent tweets with a specific hashtag using v2 API.
        
        Args:
            hashtag: Hashtag to search for (without the # symbol)
            max_results: Maximum number of results to return
        
        Returns:
            Dict[str, Any]: Twitter API response with tweet data
        """
        url = f"{API_V2_BASE}/tweets/search/recent"
        params = {
            'query': f'#{hashtag}',
            'max_results': max_results,
            'tweet.fields': 'created_at,author_id,public_metrics',
            'user.fields': 'created_at,public_metrics',
            'expansions': 'author_id'
        }
        
        logger.info(f"Searching recent tweets with hashtag #{hashtag} (max: {max_results})")
        
        try:
            # IMPORTANT: Use OAuth 2.0 headers for this request
            headers = self.get_oauth2_headers()
            
            start_time = time.time()
            response = requests.get(url, headers=headers, params=params, timeout=30)
            elapsed = time.time() - start_time
            
            response.raise_for_status()
            result = response.json()
            
            tweet_count = len(result.get('data', []))
            logger.info(f"Successfully found {tweet_count} tweets with #{hashtag} in {elapsed:.2f}s")
            
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Error searching tweets with hashtag #{hashtag}: {str(e)}")
            
            if hasattr(e, 'response') and e.response:
                logger.error(f"API response: {e.response.text}")
                
            return {}
    
    def get_user_by_id(self, user_id: str) -> Dict[str, Any]:
        """
        Get a user's details by their ID using v2 API.
        
        Args:
            user_id: Twitter user ID
            
        Returns:
            Dict[str, Any]: Twitter API response with user data
        """
        url = f"{API_V2_BASE}/users/{user_id}"
        params = {
            'user.fields': 'created_at,description,public_metrics'
        }
        
        logger.info(f"Getting user details for user ID: {user_id}")
        
        try:
            response = requests.get(url, headers=self.get_bearer_headers(), params=params, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if 'data' in result:
                username = result['data'].get('username', 'unknown')
                followers = result['data'].get('public_metrics', {}).get('followers_count', 0)
                created_at = result['data'].get('created_at', 'unknown')
                
                logger.info(f"Retrieved user @{username} with {followers} followers (created: {created_at})")
            else:
                logger.warning(f"User data not found in response for user ID {user_id}")
                
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting user by ID {user_id}: {str(e)}")
            
            if hasattr(e, 'response') and e.response:
                logger.error(f"API response: {e.response.text}")
                
            return {}
    
    def get_user_tweets(self, user_id: str, max_results: int = 100) -> Dict[str, Any]:
        """
        Get a user's tweets using v2 API.
        
        Args:
            user_id: Twitter user ID
            max_results: Maximum number of results to return
            
        Returns:
            Dict[str, Any]: Twitter API response with tweet data
        """
        url = f"{API_V2_BASE}/users/{user_id}/tweets"
        params = {
            'max_results': max_results,
            'tweet.fields': 'created_at,public_metrics',
            'exclude': 'retweets,replies'
        }
        
        logger.info(f"Getting tweets for user ID {user_id} (max: {max_results})")
        
        try:
            response = requests.get(url, headers=self.get_bearer_headers(), params=params, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            tweet_count = len(result.get('data', []))
            logger.info(f"Retrieved {tweet_count} tweets for user ID {user_id}")
            
            if tweet_count > 0:
                oldest_tweet_date = result['data'][-1].get('created_at', 'unknown')
                newest_tweet_date = result['data'][0].get('created_at', 'unknown')
                logger.debug(f"Tweet date range: {oldest_tweet_date} to {newest_tweet_date}")
            
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting tweets for user {user_id}: {str(e)}")
            
            if hasattr(e, 'response') and e.response:
                logger.error(f"API response: {e.response.text}")
                
            return {}
    
    def check_user_recent_engagement(self, user_id: str, days: int = 7) -> bool:
        """
        Check if a user has been active recently by checking their tweets instead of likes.
        This method uses v1.1 API with OAuth 1.0a which has more permissive access to public data.
        
        Args:
            user_id: Twitter user ID
            days: Number of days to look back
        
        Returns:
            bool: True if user has recent engagement, False otherwise
        """
        logger.info(f"Checking recent engagement for user ID {user_id} (last {days} days)")
        
        try:
            # Use v1.1 API to get user's recent tweets with OAuth 1.0a
            url = f"{API_V1_BASE}/statuses/user_timeline.json"
            params = {
                "user_id": user_id,
                "count": 5,         # Just need a few tweets
                "include_rts": True  # Include retweets to increase chance of finding activity
            }
            
            # Use OAuth 1.0a for better access to public data
            response = requests.get(url, auth=self.oauth1, params=params, timeout=30)
            
            if response.status_code == 200:
                tweets = response.json()
                
                if not tweets:
                    logger.info(f"No recent tweets found for user {user_id}")
                    return True  # Still assume active if we can't find tweets
                
                # Check if any tweets are within the time window
                now = datetime.now()
                cutoff = now - timedelta(days=days)
                
                for tweet in tweets:
                    created_at = datetime.strptime(
                        tweet['created_at'], 
                        '%a %b %d %H:%M:%S %z %Y'
                    )
                    
                    if created_at.replace(tzinfo=None) > cutoff:
                        logger.info(f"User {user_id} has tweeted within the last {days} days")
                        return True
                        
                logger.info(f"User {user_id} has tweets, but none within the last {days} days")
                return True  # Still assume active even if tweets are older
                
            else:
                logger.warning(f"Error checking user timeline: {response.status_code}")
                return True  # Assume active if API call fails
                
        except Exception as e:
            logger.error(f"Error checking user recent activity: {str(e)}")
            # Fallback: assume user is active
            return True
    
    #------------------
    # Engagement APIs
    #------------------
    
    def like_tweet(self, tweet_id: str) -> Dict[str, Any]:
        """
        Like a tweet using v2 API with OAuth 2.0.
        
        Args:
            tweet_id: Twitter tweet ID
            
        Returns:
            Dict[str, Any]: Twitter API response
        """
        # Check rate limits
        self.wait_for_rate_limit('likes', MAX_LIKES_PER_HOUR)
        
        url = f"{API_V2_BASE}/users/{self.user_id}/likes"
        data = {"tweet_id": tweet_id}
        
        logger.info(f"Liking tweet {tweet_id}")
        
        try:
            start_time = time.time()
            response = requests.post(url, headers=self.get_oauth2_headers(), json=data, timeout=30)
            elapsed = time.time() - start_time
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Successfully liked tweet {tweet_id} in {elapsed:.2f}s")
            
            # Apply random delay to avoid spam detection
            self.random_delay(MIN_DELAY_BETWEEN_LIKES, MAX_DELAY_BETWEEN_LIKES)
            
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Error liking tweet {tweet_id}: {str(e)}")
            
            if hasattr(e, 'response') and e.response:
                logger.error(f"API response: {e.response.text}")
                
            return {}
    
    def retweet(self, tweet_id: str) -> Dict[str, Any]:
        """
        Retweet a tweet using v2 API with OAuth 2.0.
        
        Args:
            tweet_id: Twitter tweet ID
            
        Returns:
            Dict[str, Any]: Twitter API response
        """
        # Check rate limits
        self.wait_for_rate_limit('retweets', MAX_RETWEETS_PER_HOUR)
        
        url = f"{API_V2_BASE}/users/{self.user_id}/retweets"
        data = {"tweet_id": tweet_id}
        
        logger.info(f"Retweeting tweet {tweet_id}")
        
        try:
            start_time = time.time()
            response = requests.post(url, headers=self.get_oauth2_headers(), json=data, timeout=30)
            elapsed = time.time() - start_time
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Successfully retweeted tweet {tweet_id} in {elapsed:.2f}s")
            
            # Apply random delay
            self.random_delay(MIN_DELAY_BETWEEN_LIKES, MAX_DELAY_BETWEEN_LIKES)
            
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Error retweeting tweet {tweet_id}: {str(e)}")
            
            if hasattr(e, 'response') and e.response:
                logger.error(f"API response: {e.response.text}")
                
            return {}
    
    def reply_to_tweet(self, tweet_id: str, text: str) -> Dict[str, Any]:
        """
        Reply to a tweet using v2 API with OAuth 2.0.
        
        Args:
            tweet_id: Twitter tweet ID
            text: Reply text
            
        Returns:
            Dict[str, Any]: Twitter API response
        """
        # Check rate limits
        self.wait_for_rate_limit('comments', MAX_COMMENTS_PER_HOUR)
        
        url = f"{API_V2_BASE}/tweets"
        data = {
            "text": text,
            "reply": {"in_reply_to_tweet_id": tweet_id}
        }
        
        logger.info(f"Replying to tweet {tweet_id} with: {text[:30]}...")
        
        try:
            start_time = time.time()
            response = requests.post(url, headers=self.get_oauth2_headers(), json=data, timeout=30)
            elapsed = time.time() - start_time
            
            response.raise_for_status()
            result = response.json()
            
            reply_id = result.get('data', {}).get('id', 'unknown')
            logger.info(f"Successfully replied to tweet {tweet_id} with new tweet {reply_id} in {elapsed:.2f}s")
            
            # Apply random delay
            self.random_delay(MIN_DELAY_BETWEEN_COMMENTS, MAX_DELAY_BETWEEN_COMMENTS)
            
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Error replying to tweet {tweet_id}: {str(e)}")
            
            if hasattr(e, 'response') and e.response:
                logger.error(f"API response: {e.response.text}")
                
            return {}
    
    #------------------
    # Content Posting
    #------------------
    
    def post_tweet(self, text: str) -> Dict[str, Any]:
        """
        Post a tweet using v2 API with OAuth 2.0.
        
        Args:
            text: Tweet text
            
        Returns:
            Dict[str, Any]: Twitter API response
        """
        # Check rate limits
        self.wait_for_rate_limit('tweets', MAX_TWEETS_PER_HOUR)
        
        url = f"{API_V2_BASE}/tweets"
        data = {"text": text}
        
        logger.info(f"Posting tweet: {text[:50]}...")
        
        try:
            start_time = time.time()
            response = requests.post(url, headers=self.get_oauth2_headers(), json=data, timeout=30)
            elapsed = time.time() - start_time
            
            response.raise_for_status()
            result = response.json()
            
            tweet_id = result.get('data', {}).get('id', 'unknown')
            logger.info(f"Successfully posted tweet (ID: {tweet_id}) in {elapsed:.2f}s")
            
            # Apply random delay
            self.random_delay(MIN_DELAY_BETWEEN_TWEETS, MAX_DELAY_BETWEEN_TWEETS)
            
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Error posting tweet: {str(e)}")
            
            if hasattr(e, 'response') and e.response:
                logger.error(f"API response: {e.response.text}")
                
            return {}
    
    def _upload_media(self, media_path: str) -> Optional[str]:
        """
        Upload media to Twitter using v1.1 API with OAuth 1.0a.
        
        Args:
            media_path: Path to media file
            
        Returns:
            Optional[str]: Media ID if successful, None otherwise
        """
        if not os.path.exists(media_path):
            logger.error(f"Media file not found: {media_path}")
            return None
            
        try:
            file_size = os.path.getsize(media_path)
            media_type = self._get_media_type(media_path)
            
            logger.info(f"Uploading media: {os.path.basename(media_path)} ({file_size/1024:.1f} KB, type: {media_type})")
            
            # Initialize upload
            init_url = f"{UPLOAD_URL}"
            init_data = {
                'command': 'INIT',
                'total_bytes': file_size,
                'media_type': media_type
            }
            
            logger.debug(f"Initializing media upload for {os.path.basename(media_path)}")
            start_time = time.time()
            response = requests.post(init_url, auth=self.oauth1, data=init_data, timeout=30)
            response.raise_for_status()
            media_id = response.json()['media_id']
            init_time = time.time() - start_time
            
            logger.debug(f"Media upload initialized with ID {media_id} in {init_time:.2f}s")
            
            # Upload media in chunks
            with open(media_path, 'rb') as media_file:
                chunk_size = 4 * 1024 * 1024  # 4MB chunks
                bytes_sent = 0
                segment_index = 0
                upload_start_time = time.time()
                
                while bytes_sent < file_size:
                    chunk = media_file.read(chunk_size)
                    if not chunk:
                        break
                    
                    append_url = f"{UPLOAD_URL}"
                    append_data = {
                        'command': 'APPEND',
                        'media_id': media_id,
                        'segment_index': segment_index
                    }
                    
                    chunk_start = time.time()
                    logger.debug(f"Uploading chunk {segment_index + 1} ({len(chunk)/1024:.1f} KB) for {os.path.basename(media_path)}")
                    response = requests.post(
                        append_url,
                        auth=self.oauth1,
                        data=append_data,
                        files={'media': chunk},
                        timeout=60  # Longer timeout for media upload
                    )
                    response.raise_for_status()
                    chunk_time = time.time() - chunk_start
                    
                    bytes_sent += len(chunk)
                    segment_index += 1
                    logger.debug(f"Chunk {segment_index} uploaded in {chunk_time:.2f}s ({bytes_sent/file_size*100:.1f}% complete)")
            
            upload_time = time.time() - upload_start_time
            logger.debug(f"All chunks uploaded in {upload_time:.2f}s")
            
            # Finalize upload
            finalize_url = f"{UPLOAD_URL}"
            finalize_data = {
                'command': 'FINALIZE',
                'media_id': media_id
            }
            
            logger.debug(f"Finalizing media upload for {os.path.basename(media_path)}")
            finalize_start = time.time()
            response = requests.post(finalize_url, auth=self.oauth1, data=finalize_data, timeout=30)
            response.raise_for_status()
            finalize_time = time.time() - finalize_start
            
            total_time = time.time() - start_time
            logger.info(f"Successfully uploaded media: {os.path.basename(media_path)} (ID: {media_id}) in {total_time:.2f}s")
            
            return media_id
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API error uploading media {media_path}: {str(e)}")
            
            if hasattr(e, 'response') and e.response:
                logger.error(f"API response: {e.response.text}")
                
            return None
        except Exception as e:
            logger.error(f"Unexpected error uploading media {media_path}: {str(e)}")
            return None
    
    def post_tweet_with_media(self, text: str, media_path: str) -> Dict[str, Any]:
        """
        Post a tweet with media using v1.1 API for media upload and v2 API for tweet.
        
        Args:
            text: Tweet text
            media_path: Path to media file
        
        Returns:
            Dict[str, Any]: Twitter API response
        """
        # Check rate limits
        self.wait_for_rate_limit('tweets_with_media', MAX_TWEETS_WITH_MEDIA_PER_HOUR)
        
        logger.info(f"Preparing to post tweet with media: {os.path.basename(media_path)}")
        logger.debug(f"Tweet text: {text[:50]}...")
        
        # Upload media first
        media_id = self._upload_media(media_path)
        if not media_id:
            logger.error("Failed to upload media, cannot post tweet")
            return {}
        
        auth = OAuth1(
            TWITTER_API_KEY,
            client_secret=TWITTER_API_SECRET,
            resource_owner_key=TWITTER_ACCESS_TOKEN,
            resource_owner_secret=TWITTER_ACCESS_SECRET
        )
        
        url = f"{API_V2_BASE}/tweets"
        data = {
            "text": text,
            "media": {"media_ids": [str(media_id)]}
        }
        
        try:
            logger.info(f"Posting tweet with media ID {media_id} using OAuth 1.0a")
            start_time = time.time()
            
            # Use JSON data and OAuth 1.0a auth
            response = requests.post(
                url, 
                auth=auth,
                json=data, 
                timeout=30
            )
            
            elapsed = time.time() - start_time
            
            # Check for errors
            if response.status_code != 200 and response.status_code != 201:
                logger.error(f"Error posting tweet with media: {response.status_code}")
                try:
                    error_data = response.json()
                    logger.error(f"Error details: {json.dumps(error_data)}")
                except:
                    logger.error(f"Response text: {response.text}")
                return {}
            
            result = response.json()
            
            tweet_id = result.get('data', {}).get('id', 'unknown')
            logger.info(f"Successfully posted tweet with media (Tweet ID: {tweet_id}) in {elapsed:.2f}s")
            
            # Apply random delay
            self.random_delay(MIN_DELAY_BETWEEN_TWEETS, MAX_DELAY_BETWEEN_TWEETS)
            
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Error posting tweet with media: {str(e)}")
            
            if hasattr(e, 'response') and e.response:
                logger.error(f"API response: {e.response.text}")
                
            return {}
    
    def send_dm_to_user(self, recipient_id: str, text: str) -> Dict[str, Any]:
        """
        Send a direct message using v1.1 API with OAuth 1.0a.
        
        Args:
            recipient_id: Twitter user ID of recipient
            text: DM text
            
        Returns:
            Dict[str, Any]: Twitter API response
        """
        # Check rate limits
        self.wait_for_rate_limit('dms', MAX_DMS_PER_HOUR)
        
        url = f"{API_V1_BASE}/direct_messages/events/new.json"
        data = {
            "event": {
                "type": "message_create",
                "message_create": {
                    "target": {"recipient_id": recipient_id},
                    "message_data": {"text": text}
                }
            }
        }
        
        logger.info(f"Sending DM to user {recipient_id}: {text[:30]}...")
        
        try:
            start_time = time.time()
            response = requests.post(url, auth=self.oauth1, json=data, timeout=30)
            elapsed = time.time() - start_time
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Successfully sent DM to {recipient_id} in {elapsed:.2f}s")
            
            # Apply random delay
            self.random_delay(MIN_DELAY_BETWEEN_DMS, MAX_DELAY_BETWEEN_DMS)
            
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending DM to {recipient_id}: {str(e)}")
            
            if hasattr(e, 'response') and e.response:
                logger.error(f"API response: {e.response.text}")
                
            return {}
    
    #------------------
    # Helper Methods
    #------------------
    
    def _get_media_type(self, media_path: str) -> str:
        """
        Determine the MIME type of the media file.
        
        Args:
            media_path: Path to media file
            
        Returns:
            str: MIME type
            
        Raises:
            ValueError: If the media type is not supported
        """
        extension = os.path.splitext(media_path)[1].lower()
        if extension in ['.jpg', '.jpeg']:
            return 'image/jpeg'
        elif extension == '.png':
            return 'image/png'
        elif extension == '.gif':
            return 'image/gif'
        elif extension in ['.mp4', '.mov']:
            return 'video/mp4'
        else:
            error_msg = f"Unsupported media type: {extension}"
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the TwitterAPI.
        
        Returns:
            Dict[str, Any]: Status information
        """
        current_time = time.time()
        uptime = current_time - self.init_time
        
        # Format uptime nicely
        uptime_str = f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m {int(uptime % 60)}s"
        
        status = {
            'initialized': True,
            'uptime_seconds': uptime,
            'uptime': uptime_str,
            'oauth2_token': {
                'available': bool(self.oauth2_token),
                'valid': self.token_expiry > current_time,
                'expiry': datetime.fromtimestamp(self.token_expiry).isoformat(),
                'expiry_seconds': max(0, self.token_expiry - current_time)
            },
            'rate_limits': {
                action: {
                    'count': data['count'],
                    'max': globals()[f'MAX_{action.upper()}_PER_HOUR'],
                    'reset_time': datetime.fromtimestamp(data['reset_time']).isoformat()
                }
                for action, data in self.rate_limits.items()
            },
            'user_id': self.user_id
        }
        
        logger.debug(f"API Status: Uptime {uptime_str}, Token valid: {status['oauth2_token']['valid']}")
        return status


#------------------
# OAuth 2.0 Flow
#------------------

# Generate a code verifier and code challenge for PKCE
def generate_code_verifier() -> str:
    """
    Generate a code verifier for PKCE.
    
    Returns:
        str: Code verifier
    """
    return secrets.token_urlsafe(64)

def generate_code_challenge(verifier: str) -> str:
    """
    Generate a code challenge from a code verifier for PKCE.
    
    Args:
        verifier: Code verifier
        
    Returns:
        str: Code challenge
    """
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('utf-8')
    return challenge

# For demonstration purposes, using global variables for code_verifier and code_challenge.
# In production, these should also be stored per user session.
code_verifier = generate_code_verifier()
code_challenge = generate_code_challenge(code_verifier)

@app.route("/")
def index():
    """
    Redirects the user to Twitter's OAuth 2.0 authorization endpoint.
    
    Returns:
        str: HTML page with authorization link
    """
    state_value = secrets.token_urlsafe(16)
    session['state_value'] = state_value  # Store state in session

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state_value,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256"
    }
    auth_redirect_url = f"{AUTH_URL}?{urlencode(params)}"
    logger.info(f"Redirecting to Twitter authorization URL")
    
    return f"""
    <html>
    <head>
        <title>Twitter OAuth 2.0 Authorization</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
            h1 {{ color: #1DA1F2; }}
            .btn {{ display: inline-block; background: #1DA1F2; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Twitter OAuth 2.0 Authorization</h1>
            <p>Click the button below to authorize your Twitter bot:</p>
            <a href="{auth_redirect_url}" class="btn">Authorize with Twitter</a>
        </div>
    </body>
    </html>
    """

@app.route("/callback")
def callback():
    """
    Handles the callback from Twitter, exchanges the code for an access token,
    and returns the token details.
    
    Returns:
        str: HTML page with authorization result
    """
    logger.info(f"Callback received with args: {request.args}")
    
    error = request.args.get("error")
    if error:
        logger.error(f"Error in callback: {error}")
        return f"""
        <html>
        <head>
            <title>Authorization Failed</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
                .container {{ max-width: 800px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
                h1 {{ color: #dc3545; }}
                .error {{ color: #dc3545; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Authorization Failed</h1>
                <p class="error">Error: {error}</p>
                <p>Please try again.</p>
            </div>
        </body>
        </html>
        """

    code = request.args.get("code")
    state = request.args.get("state")
    logger.info(f"Received code: {code[:10]}..., state: {state}")

    # Validate state from session
    expected_state = session.get('state_value')
    if state != expected_state:
        logger.error(f"State mismatch! Expected {expected_state} but got {state}")
        return """
        <html>
        <head>
            <title>Authorization Failed</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
                .container { max-width: 800px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
                h1 { color: #dc3545; }
                .error { color: #dc3545; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Authorization Failed</h1>
                <p class="error">Error: State mismatch</p>
                <p>Please try again.</p>
            </div>
        </body>
        </html>
        """

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": code_verifier
    }
    
    auth_tuple = (CLIENT_ID, CLIENT_SECRET)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    try:
        token_response = requests.post(TOKEN_URL, data=data, headers=headers, auth=auth_tuple, timeout=30)
        token_response.raise_for_status()
        
        token_data = token_response.json()
        logger.info(f"Successfully obtained OAuth 2.0 tokens")
        
        # Save tokens to environment variables
        os.environ["OAUTH_2_ACCESS_TOKEN"] = token_data.get('access_token')
        os.environ["OAUTH_2_REFRESH_TOKEN"] = token_data.get('refresh_token')
        os.environ["TOKEN_EXPIRY"] = str(time.time() + token_data.get('expires_in', 7200))
        
        # Try to update .env file
        try:
            env_path = '.env'
            
            # Read the current .env file
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    lines = f.readlines()
            else:
                lines = []
            
            # Find and update the token lines
            updated_access = False
            updated_refresh = False
            updated_expiry = False
            
            for i, line in enumerate(lines):
                if line.startswith('OAUTH_2_ACCESS_TOKEN=') or line.startswith('TWITTER_OAUTH2_ACCESS_TOKEN='):
                    lines[i] = f'OAUTH_2_ACCESS_TOKEN={token_data.get("access_token")}\n'
                    updated_access = True
                elif line.startswith('OAUTH_2_REFRESH_TOKEN=') or line.startswith('TWITTER_OAUTH2_REFRESH_TOKEN='):
                    lines[i] = f'OAUTH_2_REFRESH_TOKEN={token_data.get("refresh_token")}\n'
                    updated_refresh = True
                elif line.startswith('TOKEN_EXPIRY='):
                    lines[i] = f'TOKEN_EXPIRY={str(time.time() + token_data.get("expires_in", 7200))}\n'
                    updated_expiry = True
            
            # Add lines if they don't exist
            if not updated_access:
                lines.append(f'OAUTH_2_ACCESS_TOKEN={token_data.get("access_token")}\n')
            if not updated_refresh:
                lines.append(f'OAUTH_2_REFRESH_TOKEN={token_data.get("refresh_token")}\n')
            if not updated_expiry:
                lines.append(f'TOKEN_EXPIRY={str(time.time() + token_data.get("expires_in", 7200))}\n')
            
            # Write the updated file
            with open(env_path, 'w') as f:
                f.writelines(lines)
                
            logger.info("Updated .env file with new tokens")
        except Exception as e:
            logger.error(f"Error updating .env file: {str(e)}")
        
        # Display a user-friendly page with the token details
        expires_in = token_data.get('expires_in', 7200)
        expiry_time = datetime.now() + timedelta(seconds=expires_in)
        
        return f"""
        <!doctype html>
        <html>
        <head>
            <title>Twitter OAuth 2.0 Success</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
                .container {{ max-width: 800px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
                h1 {{ color: #1DA1F2; }}
                .token {{ background: #f5f8fa; padding: 15px; border-radius: 5px; word-break: break-all; }}
                .info {{ margin-bottom: 20px; }}
                .expires {{ font-style: italic; color: #657786; }}
                .success {{ color: #28a745; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Authentication Successful!</h1>
                <div class="info">
                    <p class="success">Your Twitter OAuth 2.0 authentication was successful. Here are your tokens:</p>
                </div>
                <h2>Access Token</h2>
                <div class="token">{token_data.get('access_token')}</div>
                <h2>Refresh Token</h2>
                <div class="token">{token_data.get('refresh_token')}</div>
                <p class="expires">Token expires in {expires_in} seconds (at {expiry_time.strftime('%Y-%m-%d %H:%M:%S')}).</p>
                <div class="info">
                    <p>You can now close this window and return to your application.</p>
                    <p>These tokens have been saved to your environment variables and .env file.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error exchanging code for token: {str(e)}")
        
        error_message = str(e)
        if hasattr(e, 'response') and e.response:
            try:
                error_data = e.response.json()
                error_message = error_data.get('error_description', error_data.get('error', error_message))
            except:
                pass
                
        return f"""
        <html>
        <head>
            <title>Authorization Failed</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
                .container {{ max-width: 800px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
                h1 {{ color: #dc3545; }}
                .error {{ color: #dc3545; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Authorization Failed</h1>
                <p class="error">Error exchanging code for token: {error_message}</p>
                <p>Please try again.</p>
            </div>
        </body>
        </html>
        """

@app.route("/test")
def test():
    """
    Simple test endpoint to verify the server is running.
    
    Returns:
        str: Success message
    """
    return "Hello from Flask!", 200


# Function to run the OAuth server
def run_auth_server():
    """Run the OAuth 2.0 server for token acquisition."""
    import webbrowser
    
    port = int(os.getenv("OAUTH_SERVER_PORT", 5000))
    
    # Open browser to start the OAuth flow
    webbrowser.open(f"http://127.0.0.1:{port}")
    
    # Run the Flask app
    app.run(debug=False, host="0.0.0.0", port=port)


# Main function for testing the TwitterAPI
if __name__ == "__main__":
    # If run directly, start the OAuth server
    oauth_mode = os.getenv("OAUTH_MODE", "false").lower() in ("true", "1", "yes")
    
    if oauth_mode:
        logger.info("Starting OAuth 2.0 server for token acquisition")
        run_auth_server()
    else:
        # Test the TwitterAPI functions
        logger.info("Testing TwitterAPI functions")
        twitter = TwitterAPI()
        
        # Force token refresh if needed
        logger.info("Checking and refreshing token if needed")
        twitter.refresh_oauth2_token_if_needed()
        
        # Get API status
        status = twitter.get_status()
        print(json.dumps(status, indent=2))
        
        # Example: Search for tweets with a hashtag
        tweets = twitter.search_recent_tweets("Kickstarter", max_results=10)
        print(f"Found {len(tweets.get('data', []))} tweets with #Kickstarter")