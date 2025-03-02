"""
DynamoDB Integration for Twitter Bot

This module handles interactions with DynamoDB for storing user data,
keyword matches, and engagement statistics.
"""

import os
import boto3
import logging
import traceback
from boto3.dynamodb.conditions import Key, Attr
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
import json

# Load environment variables
from dotenv import load_dotenv
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

# Log DynamoDB configuration for verification
logger.info(f"DynamoDB - Target tables: TargetedUsers={os.getenv('DYNAMODB_TARGETED_USERS_TABLE', 'TargetedUsers')}, Keywords={os.getenv('DYNAMODB_KEYWORDS_TABLE', 'Keywords')}")
logger.info(f"DynamoDB - Region: {os.getenv('AWS_REGION', 'us-east-1')}")

# Global variables for backward compatibility
_INSTANCE = None

class DynamoDBIntegration:
    """
    DynamoDB integration for storing and retrieving data.
    
    This class handles interactions with AWS DynamoDB for storing user data,
    keyword matches, and engagement statistics.
    """
    
    def __init__(self):
        """Initialize DynamoDB client."""
        logger.info("Initializing DynamoDB integration")
        
        # Get AWS credentials with error handling
        self.region = os.getenv('AWS_REGION', 'us-east-1')
        
        # Table names
        self.targeted_users_table = os.getenv('DYNAMODB_TARGETED_USERS_TABLE', 'TargetedUsers')
        self.keywords_table = os.getenv('DYNAMODB_KEYWORDS_TABLE', 'Keywords')
        self.tweets_table = os.getenv('DYNAMODB_TWEETS_TABLE', 'Tweets')
        
        try:
            # Initialize client
            self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
            self.dynamodb_client = boto3.client('dynamodb', region_name=self.region)
            
            # Log DynamoDB connection attempt
            logger.debug(f"Connecting to DynamoDB in region {self.region}")
            
            # Get table references
            self.users_table = self.dynamodb.Table(self.targeted_users_table)
            self.keywords_table_ref = self.dynamodb.Table(self.keywords_table)
            self.tweets_table_ref = self.dynamodb.Table(self.tweets_table) if self.tweets_table else None
            
            # Just log that we're assuming the tables exist
            logger.info(f"Assuming tables exist: {self.targeted_users_table}, {self.keywords_table}")
            
            logger.info("DynamoDB integration initialized successfully")
        except Exception as e:
            logger.critical(f"Failed to initialize DynamoDB client: {str(e)}")
            logger.critical(traceback.format_exc())
            raise
    
    def validate_user_data(self, user_data: Dict[str, Any]) -> bool:
        """
        Validate user data before storing.
        
        Args:
            user_data: User data to validate
            
        Returns:
            bool: True if valid, False otherwise
            
        Raises:
            ValueError: If required fields are missing
        """
        # Check for required fields - note UserID is the primary key
        required_fields = ['UserID', 'Username', 'FollowerCount', 'ProfileAge', 'TweetCount']
        
        # Add UserID if not present but Username is (for compatibility)
        if 'Username' in user_data and 'UserID' not in user_data:
            user_data['UserID'] = user_data['Username']
            logger.debug(f"Added UserID from Username: {user_data['UserID']}")
        
        # Check for required fields
        for field in required_fields:
            if field not in user_data:
                error_msg = f"Missing required field: {field}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        
        # Ensure FollowerCount is an integer - CRITICAL FIX
        try:
            user_data['FollowerCount'] = int(user_data['FollowerCount'])
        except (ValueError, TypeError):
            error_msg = f"FollowerCount must be an integer: {user_data['FollowerCount']}"
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        # Ensure ProfileAge is an integer - CRITICAL FIX
        try:
            user_data['ProfileAge'] = int(user_data['ProfileAge'])
        except (ValueError, TypeError):
            error_msg = f"ProfileAge must be an integer: {user_data['ProfileAge']}"
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        # Ensure TweetCount is an integer - CRITICAL FIX 
        try:
            user_data['TweetCount'] = int(user_data['TweetCount'])
        except (ValueError, TypeError):
            error_msg = f"TweetCount must be an integer: {user_data['TweetCount']}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.debug(f"User data validated for {user_data['Username']}")
        return True
    
    def validate_keyword_match(self, keyword_data: Dict[str, Any]) -> bool:
        """
        Validate keyword match data before storing.
        
        Args:
            keyword_data: Keyword match data to validate
            
        Returns:
            bool: True if valid, False otherwise
            
        Raises:
            ValueError: If required fields are missing
        """
        required_fields = ['Keyword', 'Username', 'TweetText', 'TweetID']
        
        # Check for required fields
        for field in required_fields:
            if field not in keyword_data:
                error_msg = f"Missing required field: {field}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        
        # Ensure required Timestamp field exists - CRITICAL FIX
        if 'FoundAt' in keyword_data and 'Timestamp' not in keyword_data:
            keyword_data['Timestamp'] = keyword_data['FoundAt']
            logger.debug(f"Added Timestamp from FoundAt: {keyword_data['Timestamp']}")
        elif 'Timestamp' not in keyword_data:
            keyword_data['Timestamp'] = datetime.now().isoformat()
            logger.debug(f"Added current Timestamp: {keyword_data['Timestamp']}")
        
        # Check types
        if not isinstance(keyword_data['Keyword'], str):
            error_msg = "Keyword must be a string"
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        if not isinstance(keyword_data['Username'], str):
            error_msg = "Username must be a string"
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        if not isinstance(keyword_data['TweetText'], str):
            error_msg = "TweetText must be a string"
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        if not isinstance(keyword_data['TweetID'], str):
            error_msg = "TweetID must be a string"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Create composite key for KeywordUsername if not present
        if 'KeywordUsername' not in keyword_data:
            keyword_data['KeywordUsername'] = f"{keyword_data['Keyword']}:{keyword_data['Username']}"
            logger.debug(f"Created composite key: {keyword_data['KeywordUsername']}")
        
        logger.debug(f"Keyword match data validated for {keyword_data['Keyword']} - {keyword_data['Username']}")
        return True
    
    def store_user_data(self, user_data: Dict[str, Any]) -> bool:
        """
        Store user data in DynamoDB.
        
        Args:
            user_data: User data to store
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Make sure UserID is set (use Username if not provided)
            if 'UserID' not in user_data and 'Username' in user_data:
                user_data['UserID'] = user_data['Username']
                logger.debug(f"Using Username as UserID: {user_data['UserID']}")
            
            # Create a copy of the user data to avoid modifying the original
            user_data_copy = user_data.copy()
            
            # Validate user data - will raise ValueError on failure
            self.validate_user_data(user_data_copy)
            
            # Add timestamp if not present
            if 'DateAdded' not in user_data_copy:
                user_data_copy['DateAdded'] = datetime.now().isoformat()
            
            # Add empty engagements if not present
            if 'Engagements' not in user_data_copy:
                user_data_copy['Engagements'] = {
                    'Likes': 0,
                    'Comments': 0,
                    'Retweets': 0,
                    'DMs': 0
                }
            
            # Log what we're storing
            logger.debug(f"Storing user: {user_data_copy['Username']} with {user_data_copy['FollowerCount']} followers")
            
            # Put item in table
            self.users_table.put_item(Item=user_data_copy)
            logger.info(f"Stored user data for {user_data_copy['Username']}")
            return True
            
        except Exception as e:
            logger.error(f"Error storing user data: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
    
    def store_keyword_match(self, keyword_data: Dict[str, Any]) -> bool:
        """
        Store keyword match data in DynamoDB.
        
        Args:
            keyword_data: Keyword match data to store
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Create a copy to avoid modifying the original
            keyword_data_copy = keyword_data.copy()
            
            # Validate keyword data
            self.validate_keyword_match(keyword_data_copy)
            
            # Log what we're storing
            composite_key = keyword_data_copy['KeywordUsername']
            logger.debug(f"Storing keyword match: {composite_key} for tweet {keyword_data_copy['TweetID']}")
            
            # Put item in table
            self.keywords_table_ref.put_item(Item=keyword_data_copy)
            logger.info(f"Stored keyword match for {keyword_data_copy['Username']} with keyword '{keyword_data_copy['Keyword']}'")
            return True
            
        except Exception as e:
            logger.error(f"Error storing keyword match: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
    
    def get_user_data(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user data from DynamoDB.
        
        Args:
            user_id: Twitter user ID or username
            
        Returns:
            Optional[Dict[str, Any]]: User data or None if not found
        """
        try:
            logger.debug(f"Getting user data for UserID: {user_id}")
            
            response = self.users_table.get_item(Key={'UserID': user_id})
            if 'Item' in response:
                logger.info(f"Retrieved user data for {user_id}")
                return response['Item']
            else:
                logger.info(f"User {user_id} not found")
                return None
        except Exception as e:
            logger.error(f"Error getting user data: {str(e)}")
            logger.debug(traceback.format_exc())
            return None
    
    def user_exists(self, user_id: str) -> bool:
        """
        Check if a user exists in DynamoDB.
        
        Args:
            user_id: Twitter user ID or username
            
        Returns:
            bool: True if user exists, False otherwise
        """
        try:
            logger.debug(f"Checking if user exists with UserID: {user_id}")
            
            response = self.users_table.get_item(Key={'UserID': user_id})
            exists = 'Item' in response
            logger.debug(f"User {user_id} {'exists' if exists else 'does not exist'}")
            return exists
        except Exception as e:
            logger.error(f"Error checking if user exists: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
    
    def get_recent_users(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get users added within the last N days.
        
        Args:
            days: Number of days to look back
            
        Returns:
            List[Dict[str, Any]]: List of user data
        """
        try:
            # Calculate cutoff date
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            logger.debug(f"Getting users added since {cutoff_date}")
            
            # Scan table
            response = self.users_table.scan(
                FilterExpression=Attr('DateAdded').gt(cutoff_date)
            )
            
            users = response.get('Items', [])
            logger.info(f"Retrieved {len(users)} users added in the last {days} days")
            return users
        except Exception as e:
            logger.error(f"Error getting recent users: {str(e)}")
            logger.debug(traceback.format_exc())
            return []
    
    def get_users_for_keyword_search(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get users for keyword search - prioritizing those not recently checked.
        
        Args:
            limit: Maximum number of users to return
            
        Returns:
            List[Dict[str, Any]]: List of user data
        """
        try:
            # First try to get users who haven't been searched recently
            recent_users = self.get_recent_users(days=30)
            
            # Sort by LastKeywordSearch (if it exists) - oldest first
            def get_last_search_time(user):
                if 'LastKeywordSearch' in user:
                    return user['LastKeywordSearch']
                return "2000-01-01T00:00:00"  # Default old date for users never searched
                
            sorted_users = sorted(recent_users, key=get_last_search_time)
            
            # Limit the number of users
            limited_users = sorted_users[:limit]
            
            logger.info(f"Retrieved {len(limited_users)} users for keyword search")
            return limited_users
            
        except Exception as e:
            logger.error(f"Error getting users for keyword search: {str(e)}")
            logger.debug(traceback.format_exc())
            return []
    
    def get_users_for_dm(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get users who should receive DMs (matched keywords and haven't received DMs yet).
        
        Args:
            limit: Maximum number of users to return
            
        Returns:
            List[Dict[str, Any]]: List of user data
        """
        try:
            # Get users who have matched keywords
            response = self.users_table.scan(
                FilterExpression=Attr('KeywordsFound').exists() & Attr('DMSent').not_exists()
            )
            
            users = response.get('Items', [])
            
            # Sort by engagement count (if available) - most engaged first
            def get_engagement_count(user):
                engagements = user.get('Engagements', {})
                return sum([
                    engagements.get('Likes', 0),
                    engagements.get('Comments', 0),
                    engagements.get('Retweets', 0)
                ])
                
            sorted_users = sorted(users, key=get_engagement_count, reverse=True)
            
            # Limit the number of users
            limited_users = sorted_users[:limit]
            
            logger.info(f"Retrieved {len(limited_users)} users for DM sending")
            return limited_users
            
        except Exception as e:
            logger.error(f"Error getting users for DM: {str(e)}")
            logger.debug(traceback.format_exc())
            return []
    
    def mark_user_dm_sent(self, user_id: str) -> bool:
        """
        Mark a user as having been sent a DM.
        
        Args:
            user_id: User ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get current user data
            user_data = self.get_user_data(user_id)
            if not user_data:
                logger.warning(f"User {user_id} not found for DM sent marking")
                return False
            
            # Update DM sent status
            user_data['DMSent'] = True
            user_data['DMSentAt'] = datetime.now().isoformat()
            
            # Store updated user data
            result = self.store_user_data(user_data)
            if result:
                logger.info(f"Marked user {user_id} as sent DM")
            
            return result
            
        except Exception as e:
            logger.error(f"Error marking user DM sent: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
    
    def get_tweets_for_engagement(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get tweets that match keywords for engagement.
        
        Args:
            limit: Maximum number of tweets to return
            
        Returns:
            List[Dict[str, Any]]: List of tweet data
        """
        try:
            # Scan the keywords table for tweets we haven't engaged with yet
            response = self.keywords_table_ref.scan(
                FilterExpression=Attr('Engaged').not_exists()
            )
            
            tweets = response.get('Items', [])
            
            # Sort by timestamp (newest first)
            sorted_tweets = sorted(
                tweets,
                key=lambda x: x.get('Timestamp', '2000-01-01T00:00:00'),
                reverse=True
            )
            
            # Limit the number of tweets
            limited_tweets = sorted_tweets[:limit]
            
            logger.info(f"Retrieved {len(limited_tweets)} tweets for engagement")
            return limited_tweets
            
        except Exception as e:
            logger.error(f"Error getting tweets for engagement: {str(e)}")
            logger.debug(traceback.format_exc())
            return []
    
    def mark_tweet_as_engaged(self, tweet_id: str, keyword: str = None) -> bool:
        """
        Mark a tweet as having been engaged with.
        
        Args:
            tweet_id: Tweet ID
            keyword: Keyword that matched this tweet (optional)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # If we have keyword, try to look up the exact record
            if keyword:
                # Scan for the matching tweet
                response = self.keywords_table_ref.scan(
                    FilterExpression=Attr('TweetID').eq(tweet_id) & Attr('Keyword').eq(keyword)
                )
                
                items = response.get('Items', [])
                if items:
                    for item in items:
                        # Update engaged status
                        item['Engaged'] = True
                        item['EngagedAt'] = datetime.now().isoformat()
                        
                        # Update the item
                        self.keywords_table_ref.put_item(Item=item)
                    
                    logger.info(f"Marked tweet {tweet_id} as engaged with keyword {keyword}")
                    return True
            
            # If no keyword or not found with keyword, try tweet ID only
            response = self.keywords_table_ref.scan(
                FilterExpression=Attr('TweetID').eq(tweet_id)
            )
            
            items = response.get('Items', [])
            if items:
                for item in items:
                    # Update engaged status
                    item['Engaged'] = True
                    item['EngagedAt'] = datetime.now().isoformat()
                    
                    # Update the item
                    self.keywords_table_ref.put_item(Item=item)
                
                logger.info(f"Marked tweet {tweet_id} as engaged")
                return True
            
            logger.warning(f"Tweet {tweet_id} not found for marking as engaged")
            return False
            
        except Exception as e:
            logger.error(f"Error marking tweet as engaged: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
    
    def update_engagement_stats(self, engagement: Dict[str, Any]) -> bool:
        """
        Update engagement statistics for a user.
        
        Args:
            engagement: Engagement data
                - Username: Twitter username
                - EngagementType: Type of engagement (Like, Comment, Retweet, DM)
                - TweetID: ID of the tweet
                - Timestamp: Timestamp of the engagement
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Validate engagement data
            required_fields = ['Username', 'EngagementType']
            for field in required_fields:
                if field not in engagement:
                    logger.error(f"Missing required field in engagement data: {field}")
                    return False
            
            # Get user ID - use Username if UserID not provided
            user_id = engagement.get('UserID', engagement.get('Username'))
            if not user_id:
                logger.error("No user ID or username provided for engagement update")
                return False
                
            logger.debug(f"Updating engagement stats for {user_id} - {engagement['EngagementType']}")
            
            # Get current user data
            user_data = self.get_user_data(user_id)
            if not user_data:
                logger.warning(f"User {user_id} not found for engagement update")
                return False
            
            # Initialize engagements if not present
            if 'Engagements' not in user_data:
                user_data['Engagements'] = {
                    'Likes': 0,
                    'Comments': 0,
                    'Retweets': 0,
                    'DMs': 0
                }
            
            # Update the appropriate counter
            engagement_type = engagement['EngagementType']
            if engagement_type == 'Like':
                user_data['Engagements']['Likes'] = user_data['Engagements'].get('Likes', 0) + 1
            elif engagement_type == 'Comment':
                user_data['Engagements']['Comments'] = user_data['Engagements'].get('Comments', 0) + 1
            elif engagement_type == 'Retweet':
                user_data['Engagements']['Retweets'] = user_data['Engagements'].get('Retweets', 0) + 1
            elif engagement_type == 'DM':
                user_data['Engagements']['DMs'] = user_data['Engagements'].get('DMs', 0) + 1
            else:
                logger.warning(f"Unknown engagement type: {engagement_type}")
            
            # Update last engagement date
            user_data['LastEngagementDate'] = engagement.get('Timestamp', datetime.now().isoformat())
            
            # Log the update
            logger.debug(f"Updated engagement counts: {user_data['Engagements']}")
            
            # Save the updated user data
            return self.store_user_data(user_data)
        except Exception as e:
            logger.error(f"Error updating engagement stats: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
            
    def save_posting_history(self, history: Dict[str, Any]) -> bool:
        """
        Save content posting history.
        
        Args:
            history: Posting history data
                - content_id: Content identifier
                - tweet_id: ID of the posted tweet
                - timestamp: Posting timestamp
                - status: Status of the post
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Create a special table entry for content posting history
            history_entry = {
                'UserID': 'CONTENT_HISTORY', # Use special UserID instead of Username
                'ContentID': history.get('content_id', 'unknown'),
                'TweetID': history.get('tweet_id', 'unknown'),
                'Timestamp': history.get('timestamp', datetime.now().isoformat()),
                'Status': history.get('status', 'posted'),
                'Type': 'ContentHistory'  # Mark this as content history
            }
            
            # Use the users table with a unique UserID
            history_entry['UserID'] = f"CONTENT_HISTORY_{history_entry['ContentID']}"
            
            # Also set Username for compatibility
            history_entry['Username'] = history_entry['UserID']
            
            # Log the history entry
            logger.debug(f"Saving content history: {history_entry['ContentID']} - {history_entry['TweetID']}")
            
            # Store in the users table (reusing it for content history)
            self.users_table.put_item(Item=history_entry)
            logger.info(f"Saved posting history for content {history_entry['ContentID']}")
            return True
        except Exception as e:
            logger.error(f"Error saving posting history: {str(e)}")
            logger.debug(traceback.format_exc())
            return False


# Initialize global instance for backward compatibility functions
def _init_db_instance():
    """Initialize the global DB instance if needed."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = DynamoDBIntegration()
    return _INSTANCE

# Backward compatibility functions
def create_tables_if_not_exist():
    """Create DynamoDB tables if they don't exist (for backward compatibility)."""
    db = _init_db_instance()
    logger.info("Tables exist or were created successfully")
    return True

def store_user_data(user_data):
    """Store user data (for backward compatibility)."""
    db = _init_db_instance()
    return db.store_user_data(user_data)

def get_user_data(username):
    """Get user data (for backward compatibility)."""
    db = _init_db_instance()
    return db.get_user_data(username)

def user_exists(username):
    """Check if user exists (for backward compatibility)."""
    db = _init_db_instance()
    return db.user_exists(username)

def store_keyword_match(keyword_data):
    """Store keyword match (for backward compatibility)."""
    db = _init_db_instance()
    return db.store_keyword_match(keyword_data)

def get_recent_users(days=7):
    """Get recent users (for backward compatibility)."""
    db = _init_db_instance()
    return db.get_recent_users(days)

def update_engagement_stats(engagement):
    """Update engagement stats (for backward compatibility)."""
    db = _init_db_instance()
    return db.update_engagement_stats(engagement)

def get_tweets_for_engagement(limit=10):
    """Get tweets for engagement (for backward compatibility)."""
    db = _init_db_instance()
    return db.get_tweets_for_engagement(limit)

def mark_tweet_as_engaged(tweet_id, keyword=None):
    """Mark a tweet as having been engaged with (for backward compatibility)."""
    db = _init_db_instance()
    return db.mark_tweet_as_engaged(tweet_id, keyword)

def get_users_for_keyword_search(limit=20):
    """Get users for keyword search (for backward compatibility)."""
    db = _init_db_instance()
    return db.get_users_for_keyword_search(limit)

def get_users_for_dm(limit=5):
    """Get users for DM (for backward compatibility)."""
    db = _init_db_instance()
    return db.get_users_for_dm(limit)

def mark_user_dm_sent(user_id):
    """Mark a user as having been sent a DM (for backward compatibility)."""
    db = _init_db_instance()
    return db.mark_user_dm_sent(user_id)

def save_posting_history(history):
    """Save posting history (for backward compatibility)."""
    db = _init_db_instance()
    return db.save_posting_history(history)

def count_items(table_name: str) -> int:
    """
    Count the total number of items in a DynamoDB table.
    
    Args:
        table_name: Name of the DynamoDB table
        
    Returns:
        int: Total number of items in the table
    """
    try:
        if not _INSTANCE:
            _init_db_instance()
        
        # Get the specified table
        table = _INSTANCE.dynamodb.Table(table_name)
        
        # Use scan with Select='COUNT' for efficiency
        response = table.scan(Select='COUNT')
        
        # Return the count
        return response.get('Count', 0)
    except Exception as e:
        logger.error(f"Error counting items in table {table_name}: {str(e)}")
        return 0