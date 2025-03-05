"""
OpenAI Integration for Twitter Bot

This module handles all AI-related operations for generating comments,
tweet text, and personalized DMs using the OpenAI API.
Focused on comic book art for a Kickstarter campaign.

Key features:
- Robust error handling for API failures
- Fallback content generation when API is unavailable
- Response validation and retry mechanisms
- Caching to minimize API usage
- Support for multiple AI models and providers
"""

import os
import logging
import base64
import json
import time
import random
import threading
import hashlib
from typing import Dict, List, Optional, Any, Union, Tuple
from datetime import datetime, timedelta
import io
import glob
import re

import openai
from openai import OpenAI
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

# Twitter character limit
TWITTER_CHAR_LIMIT = int(os.getenv('TWITTER_CHAR_LIMIT', '280'))

# OpenAI configuration
DEFAULT_MODEL = os.getenv('OPENAI_DEFAULT_MODEL', 'gpt-3.5-turbo')
VISION_MODEL = os.getenv('OPENAI_VISION_MODEL', 'gpt-4o')
MAX_RETRIES = int(os.getenv('OPENAI_MAX_RETRIES', '3'))
RETRY_DELAY = int(os.getenv('OPENAI_RETRY_DELAY', '2'))
CACHE_EXPIRY_HOURS = int(os.getenv('OPENAI_CACHE_EXPIRY_HOURS', '24'))

# Log configuration
logger.info(f"AI Integration configured with model: {DEFAULT_MODEL}, vision model: {VISION_MODEL}")
logger.info(f"Retry settings: max_retries={MAX_RETRIES}, retry_delay={RETRY_DELAY}s, cache_expiry={CACHE_EXPIRY_HOURS}h")

# Performance tracking
api_stats = {
    'calls': 0,
    'successes': 0,
    'failures': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'fallbacks_used': 0
}

# Cache lock
cache_lock = threading.Lock()

# Response cache
response_cache = {}


class AIResponseValidator:
    """
    Validator for AI-generated responses.
    
    This class validates responses from the AI to ensure they meet
    requirements like length limits, appropriate content, etc.
    """
    
    @staticmethod
    def validate_tweet_text(text: str, max_length: int = TWITTER_CHAR_LIMIT) -> Tuple[bool, str]:
        """
        Validate tweet text.
        
        Args:
            text: Text to validate
            max_length: Maximum allowed length
            
        Returns:
            Tuple[bool, str]: (is_valid, reason)
        """
        # Check length
        if len(text) > max_length:
            return False, f"Text exceeds maximum length of {max_length} characters"
        
        # Check for empty text
        if not text.strip():
            return False, "Text is empty"
        
        # Check for prohibited patterns (example: placeholder text)
        if re.search(r'\[.*?\]', text):
            return False, "Text contains placeholder markers [like this]"
        
        return True, ""
    
    @staticmethod
    def validate_comment(text: str, max_length: int = TWITTER_CHAR_LIMIT) -> Tuple[bool, str]:
        """
        Validate comment text.
        
        Args:
            text: Text to validate
            max_length: Maximum allowed length
            
        Returns:
            Tuple[bool, str]: (is_valid, reason)
        """
        # Use same validation as tweet text
        return AIResponseValidator.validate_tweet_text(text, max_length)
    
    @staticmethod
    def validate_dm(text: str, max_length: int = TWITTER_CHAR_LIMIT) -> Tuple[bool, str]:
        """
        Validate DM text.
        
        Args:
            text: Text to validate
            max_length: Maximum allowed length
            
        Returns:
            Tuple[bool, str]: (is_valid, reason)
        """
        # Use same validation as tweet text, but with additional DM-specific checks
        valid, reason = AIResponseValidator.validate_tweet_text(text, max_length)
        if not valid:
            return valid, reason
        
        # Add any DM-specific validation here
        # For example, check for appropriate greeting or signature
        
        return True, ""


class AIFallbackGenerator:
    """
    Fallback content generator for when the AI API is unavailable.
    
    This class provides simple rule-based generation of content
    when the AI API cannot be accessed.
    """
    
    @staticmethod
    def generate_tweet_text(image_path: Optional[str] = None, summary: Optional[str] = None) -> str:
        """
        Generate fallback tweet text.
        
        Args:
            image_path: Path to image (optional)
            summary: Content summary (optional)
        
        Returns:
            str: Generated tweet text
        """
        # Check if summary contains a Kickstarter link
        has_kickstarter_link = summary and ("kickstarter.com" in summary.lower() or "kck.st" in summary.lower())
        has_comic_art = summary and "comic" in summary.lower()
        
        # Generic templates without specific mentions
        general_templates = [
            "Check out our latest artwork! {summary} #art #creative",
            "New release! {summary} #artwork #creativity",
            "Just unveiled: {summary} #art #imagination",
            "Don't miss this amazing artwork! {summary} #visualart",
            "Support indie artists! {summary} #art #creative"
        ]
        
        # Templates for when Kickstarter is explicitly mentioned
        kickstarter_templates = [
            "Support our Kickstarter! {summary} #kickstarter #funding",
            "Back our campaign! {summary} #kickstarter #crowdfunding",
            "Help make this happen! {summary} #kickstarter #support",
            "Fund our project! {summary} #kickstarter #backers",
            "Join our Kickstarter campaign! {summary} #crowdfunding"
        ]
        
        # Choose appropriate template set
        if has_kickstarter_link:
            templates = kickstarter_templates
        else:
            templates = general_templates
        
        # Select a random template
        template = random.choice(templates)
        
        # Use summary if provided, otherwise create a generic one
        if not summary or len(summary.strip()) == 0:
            if image_path:
                filename = os.path.basename(image_path)
                summary = f"This amazing {filename.split('.')[0]} design"
            else:
                summary = "Amazing artwork for your collection"
        
        # Ensure summary isn't too long
        if summary and len(summary) > 100:
            summary = summary[:97] + "..."
        
        # Fill the template
        tweet = template.format(summary=summary)
        
        # Ensure it fits in Twitter's character limit
        if len(tweet) > TWITTER_CHAR_LIMIT:
            # Trim the summary to make it fit
            excess = len(tweet) - TWITTER_CHAR_LIMIT + 3  # +3 for the ellipsis
            new_summary_len = max(10, len(summary) - excess)
            summary = summary[:new_summary_len] + "..."
            tweet = template.format(summary=summary)
        
        logger.debug(f"Generated fallback tweet with length {len(tweet)}: {tweet[:30]}...")
        return tweet
    
    @staticmethod
    def generate_comment(tweet_text: str) -> str:
        """
        Generate fallback comment text.
        
        Args:
            tweet_text: Original tweet text
            
        Returns:
            str: Generated comment
        """
        # Generic supportive comments
        comments = [
            "Love this art! Looking forward to seeing more from your campaign.",
            "Great work! We're also running a comic art campaign on Kickstarter that you might enjoy.",
            "Amazing design! If you enjoy this style, check out our comic art Kickstarter.",
            "This looks fantastic! As fellow comic creators, we appreciate your work.",
            "Awesome! Our Kickstarter has similar art that might interest you."
        ]
        
        comment = random.choice(comments)
        logger.debug(f"Generated fallback comment with length {len(comment)}: {comment}")
        return comment
    
    @staticmethod
    def generate_dm(username: str, context: str) -> str:
        """
        Generate fallback DM text.
        
        Args:
            username: Twitter username
            context: DM context
            
        Returns:
            str: Generated DM text
        """
        # Generic DM templates
        templates = [
            "Hi {username}! Thanks for your interest in comic art. We have a Kickstarter campaign we thought you might enjoy. Check it out when you get a chance!",
            "Hello {username}! We noticed you're into comics. Our Kickstarter campaign features original art that might interest you. Would love your feedback!",
            "Hey {username}! As a comic art enthusiast, we wanted to share our Kickstarter campaign with you. Hope you'll check it out!"
        ]
        
        dm = random.choice(templates).format(username=username)
        
        # Ensure it fits in Twitter's character limit
        if len(dm) > TWITTER_CHAR_LIMIT:
            dm = dm[:TWITTER_CHAR_LIMIT-3] + "..."
        
        logger.debug(f"Generated fallback DM with length {len(dm)}: {dm[:30]}...")    
        return dm


class OpenAIIntegration:
    """
    OpenAI Integration for generating content for the Twitter bot.
    
    This class handles all AI-related operations for generating comments,
    tweet text, and personalized DMs using the OpenAI API.
    
    Attributes:
        api_key (str): OpenAI API key
        client (OpenAI): OpenAI client instance
        default_model (str): Default model to use for text generation
        vision_model (str): Model to use for image analysis
        cache_expiry (int): Cache expiry time in hours
    """
    
    def __init__(self):
        """Initialize OpenAI API client with robust error handling."""
        logger.info("Initializing OpenAI integration")
        
        # Get API key with error handling
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            logger.critical("Missing OpenAI API key. Please set OPENAI_API_KEY in your .env file.")
            raise ValueError("Missing OpenAI API key. Please set OPENAI_API_KEY in your .env file.")
        
        # Mask API key for logging while preserving start/end for identification
        if len(self.api_key) > 8:
            masked_key = f"{self.api_key[:4]}...{self.api_key[-4:]}"
            logger.info(f"Using OpenAI API key: {masked_key}")
        
        # Initialize client
        try:
            self.client = OpenAI(api_key=self.api_key)
            
            # Configuration
            self.default_model = DEFAULT_MODEL
            self.vision_model = VISION_MODEL
            self.cache_expiry = CACHE_EXPIRY_HOURS
            
            # Test the API connection, but skip during tests
            if os.getenv('TESTING') != 'true':
                connection_result = self._test_api_connection()
                if connection_result:
                    logger.info("Successfully connected to OpenAI API")
                else:
                    logger.warning("Failed to connect to OpenAI API - fallbacks will be used")
            
            # Initialize call counters
            self.call_count = 0
            self.success_count = 0
            self.error_count = 0
            
            logger.info("OpenAI integration initialized successfully")
        except Exception as e:
            logger.critical(f"Failed to initialize OpenAI client: {str(e)}")
            raise
    
    def _test_api_connection(self) -> bool:
        """
        Test the API connection with a simple request.
        
        Returns:
            bool: True if connection succeeded, False otherwise
        """
        try:
            # Make a minimal API call to test the connection
            # Use self.default_model instead of hardcoded 'gpt-3.5-turbo'
            logger.debug("Testing OpenAI API connection")
            start_time = time.time()
            
            self.client.chat.completions.create(
                model=self.default_model,
                messages=[
                    {"role": "system", "content": "Test connection"},
                    {"role": "user", "content": "Hello"}
                ],
                max_tokens=1
            )
            
            elapsed = time.time() - start_time
            logger.debug(f"API connection test successful in {elapsed:.2f}s")
            
            # Update stats
            with cache_lock:  # Using the same lock for stats protection
                api_stats['calls'] += 1
                api_stats['successes'] += 1
                
            return True
        except Exception as e:
            logger.warning(f"API connection test failed: {str(e)}")
            
            # Update stats
            with cache_lock:
                api_stats['calls'] += 1
                api_stats['failures'] += 1
                
            return False
    
    def truncate_to_char_limit(self, text: str, limit: int = TWITTER_CHAR_LIMIT) -> str:
        """
        Truncate text to fit Twitter's character limit, preserving meaning.
        
        Args:
            text: Text to truncate
            limit: Character limit
            
        Returns:
            str: Truncated text
        """
        if len(text) <= limit:
            return text
        
        # Try to truncate at a sentence boundary
        sentences = re.split(r'(?<=[.!?])\s+', text)
        result = ""
        
        for sentence in sentences:
            if len(result + sentence) <= limit - 3:  # -3 for ellipsis
                result += sentence + " "
            else:
                break
        
        # If we couldn't get any complete sentences, just truncate
        if not result:
            result = text[:limit - 3]
        
        # Add ellipsis and trim any trailing whitespace
        result = result.rstrip() + "..."
        
        logger.debug(f"Truncated text from {len(text)} to {len(result)} characters")
        return result
    
    def _get_cache_key(self, operation: str, **kwargs) -> str:
        """
        Generate a cache key for the given operation and parameters.
        
        Args:
            operation: Operation name (e.g., 'tweet', 'comment', 'dm')
            **kwargs: Operation parameters
            
        Returns:
            str: Cache key
        """
        # Create a string representation of the kwargs
        kwargs_str = json.dumps(kwargs, sort_keys=True)
        
        # Create a hash of the operation and kwargs
        key = hashlib.md5(f"{operation}:{kwargs_str}".encode()).hexdigest()
        
        return key
    
    def _get_cached_response(self, operation: str, **kwargs) -> Optional[str]:
        """
        Get a cached response if available and not expired.
        
        Args:
            operation: Operation name
            **kwargs: Operation parameters
            
        Returns:
            Optional[str]: Cached response or None if not found
        """
        with cache_lock:
            key = self._get_cache_key(operation, **kwargs)
            
            if key in response_cache:
                entry = response_cache[key]
                expiry_time = entry.get('expiry_time', 0)
                
                # Check if the entry has expired
                if time.time() < expiry_time:
                    logger.debug(f"Cache hit for {operation}")
                    api_stats['cache_hits'] += 1
                    return entry.get('response')
                else:
                    # Remove expired entry
                    logger.debug(f"Cache entry for {operation} has expired")
                    del response_cache[key]
            
            api_stats['cache_misses'] += 1
            return None
    
    def _cache_response(self, operation: str, response: str, **kwargs) -> None:
        """
        Cache a response for future use.
        
        Args:
            operation: Operation name
            response: Response to cache
            **kwargs: Operation parameters
        """
        with cache_lock:
            key = self._get_cache_key(operation, **kwargs)
            
            # Calculate expiry time
            expiry_time = time.time() + (self.cache_expiry * 3600)
            
            # Store in cache
            response_cache[key] = {
                'response': response,
                'expiry_time': expiry_time,
                'timestamp': time.time()
            }
            
            logger.debug(f"Cached response for {operation}, cache now has {len(response_cache)} entries")
    
    def _clean_cache(self) -> int:
        """
        Clean expired entries from the cache.
        
        Returns:
            int: Number of entries removed
        """
        with cache_lock:
            current_time = time.time()
            expired_keys = [
                key for key, entry in response_cache.items()
                if entry.get('expiry_time', 0) < current_time
            ]
            
            # Remove expired entries
            for key in expired_keys:
                del response_cache[key]
            
            if expired_keys:
                logger.debug(f"Cleaned {len(expired_keys)} expired entries from cache")
            
            return len(expired_keys)
    
    def generate_tweet_text(
        self, 
        image_path: Optional[str] = None, 
        summary: Optional[str] = None, 
        max_length: int = TWITTER_CHAR_LIMIT,
        use_cache: bool = True
    ) -> str:
        """
        Generate tweet text based on an image and summary.

        Args:
            image_path: Path to the image file (optional)
            summary: Text summary of the content (optional)
            max_length: Maximum length of the tweet
            use_cache: Whether to use cached responses

        Returns:
            str: Generated tweet text
        """
        logger.info(f"Generating tweet text with image_path={image_path is not None}, summary_length={len(summary) if summary else 0}")

        # Check cache if enabled
        if use_cache:
            cached = self._get_cached_response('tweet', image_path=image_path, summary=summary)
            if cached:
                logger.info(f"Using cached tweet text ({len(cached)} chars)")
                return self.truncate_to_char_limit(cached, max_length)

        try:
            # Clean up optional parameters
            if summary is None:
                summary = ""

            image_description = ""
            if image_path:
                # Get image filename for description
                image_description = f"Image file: {os.path.basename(image_path)}"

            # Check if summary contains a Kickstarter link
            has_kickstarter_link = "kickstarter.com" in summary.lower() or "kck.st" in summary.lower()

            # Create a prompt for OpenAI that generates natural-sounding tweets
            prompt = (
                "Write a casual, engaging tweet about this artwork as if you're a real person sharing something cool. "
                f"Image Description: {image_description}\n"
                f"Content Info: {summary}\n\n"
                f"Keep it under {max_length} characters and make it sound natural and conversational - like something a real person would actually tweet. "
                "Include a call-to-action only if it feels natural.\n\n"
                "IMPORTANT GUIDELINES:\n"
                "- Sound like a real person, not a marketer\n"
                "- Use casual language, contractions, and natural phrasing\n"
                "- Focus on what's exciting about the art itself\n"
                "- Avoid corporate or promotional-sounding language\n"
                "- Use no more than one hashtag, and only if it flows naturally\n"
            )

            # Add Kickstarter guidance based on whether a link is present
            if has_kickstarter_link:
                prompt += "- You can briefly mention backing the project on Kickstarter, but make it casual and authentic\n"
            else:
                prompt += "- Don't mention Kickstarter or crowdfunding campaigns\n"

            prompt += "3. Focus on the artwork's style, content, and emotional impact rather than medium or platform.\n"

            logger.debug(f"Tweet prompt: {prompt[:100]}...")

            # Track retry attempts
            for attempt in range(MAX_RETRIES):
                try:
                    with cache_lock:
                        api_stats['calls'] += 1

                    start_time = time.time()
                    response = self.client.chat.completions.create(
                        model=self.default_model,
                        messages=[
                            {"role": "system", "content": "You are a creative person sharing art you're excited about. You sound like a real human, not a marketing account."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.8,
                        max_tokens=60
                    )
                    elapsed = time.time() - start_time

                    tweet_text = response.choices[0].message.content.strip()

                    # Validate the response
                    valid, reason = AIResponseValidator.validate_tweet_text(tweet_text, max_length)
                    if not valid:
                        logger.warning(f"Generated invalid tweet text: {reason}. Retrying...")
                        continue

                    # Update stats
                    with cache_lock:
                        api_stats['successes'] += 1

                    # Cache the response
                    if use_cache:
                        self._cache_response('tweet', tweet_text, image_path=image_path, summary=summary)

                    logger.info(f"Generated tweet text ({len(tweet_text)} chars) in {elapsed:.2f}s: {tweet_text[:30]}...")
                    return self.truncate_to_char_limit(tweet_text, max_length)

                except openai.RateLimitError as e:
                    with cache_lock:
                        api_stats['failures'] += 1

                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Rate limit hit, retrying in {wait_time} seconds: {str(e)}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Rate limit error after {MAX_RETRIES} attempts: {str(e)}")
                        break
                except openai.APIError as e:
                    with cache_lock:
                        api_stats['failures'] += 1

                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"API error, retrying in {wait_time} seconds: {str(e)}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"API error after {MAX_RETRIES} attempts: {str(e)}")
                        break
                except Exception as e:
                    with cache_lock:
                        api_stats['failures'] += 1

                    logger.error(f"Unexpected error generating tweet text: {str(e)}")
                    break

            # If we get here, all retries failed or an unexpected error occurred
            logger.warning("Using fallback tweet text generator")
            with cache_lock:
                api_stats['fallbacks_used'] += 1

            fallback_tweet = AIFallbackGenerator.generate_tweet_text(image_path, summary)
            return self.truncate_to_char_limit(fallback_tweet, max_length)

        except Exception as e:
            logger.error(f"Error generating tweet text: {str(e)}")

            with cache_lock:
                api_stats['fallbacks_used'] += 1

            # Fallback to using the summary directly
            fallback = AIFallbackGenerator.generate_tweet_text(image_path, summary)
            return self.truncate_to_char_limit(fallback, max_length)
    
    def generate_comment(
        self, 
        tweet_text: str, 
        max_length: int = TWITTER_CHAR_LIMIT,
        use_cache: bool = True
    ) -> str:
        """
        Generate a contextually relevant comment for a tweet.
        
        Args:
            tweet_text: The tweet to comment on
            max_length: Maximum length of the comment
            use_cache: Whether to use cached responses
            
        Returns:
            str: Generated comment
        """
        logger.info(f"Generating comment for tweet: {tweet_text[:30]}...")
        
        # Check cache if enabled
        if use_cache:
            cached = self._get_cached_response('comment', tweet_text=tweet_text)
            if cached:
                logger.info(f"Using cached comment ({len(cached)} chars)")
                return self.truncate_to_char_limit(cached, max_length)
                
        try:
            if not isinstance(tweet_text, str):
                logger.error("Invalid input: tweet_text must be a string")
                return AIFallbackGenerator.generate_comment("")

            # Create a prompt for OpenAI
            prompt = (
                "Write a genuine, conversational reply to this tweet as a fellow art enthusiast:\n"
                f"Tweet: {tweet_text}\n\n"
                "Your comment should:\n"
                "- Be under 280 characters\n"
                "- Show authentic appreciation for the content\n"
                "- Sound like a real person, not a business\n"
                "- Feel like an organic conversation, not marketing\n"
                "- Avoid clichés and generic praise\n"
                "\nIf it feels natural in context, you can briefly mention your own artistic project, but only if it directly relates to what they posted about."
            )

            logger.debug(f"Comment prompt: {prompt[:100]}...")

            # Track retry attempts
            for attempt in range(MAX_RETRIES):
                try:
                    with cache_lock:
                        api_stats['calls'] += 1
                    
                    start_time = time.time()
                    response = self.client.chat.completions.create(
                        model=self.default_model,
                        messages=[
                            {"role": "system", "content": "You are an art enthusiast having natural conversations on social media. You're just a regular person, not a marketer."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.8,
                        max_tokens=40
                    )
                    elapsed = time.time() - start_time
                    
                    comment = response.choices[0].message.content.strip()
                    
                    # Validate the response
                    valid, reason = AIResponseValidator.validate_comment(comment, max_length)
                    if not valid:
                        logger.warning(f"Generated invalid comment: {reason}. Retrying...")
                        continue
                    
                    # Update stats
                    with cache_lock:
                        api_stats['successes'] += 1
                    
                    # Cache the response
                    if use_cache:
                        self._cache_response('comment', comment, tweet_text=tweet_text)
                    
                    logger.info(f"Generated comment ({len(comment)} chars) in {elapsed:.2f}s: {comment[:30]}...")
                    return self.truncate_to_char_limit(comment, max_length)
                    
                except openai.RateLimitError as e:
                    with cache_lock:
                        api_stats['failures'] += 1
                    
                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Rate limit hit, retrying in {wait_time} seconds: {str(e)}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Rate limit error after {MAX_RETRIES} attempts: {str(e)}")
                        break
                except openai.APIError as e:
                    with cache_lock:
                        api_stats['failures'] += 1
                    
                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"API error, retrying in {wait_time} seconds: {str(e)}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"API error after {MAX_RETRIES} attempts: {str(e)}")
                        break
                except Exception as e:
                    with cache_lock:
                        api_stats['failures'] += 1
                    
                    logger.error(f"Unexpected error generating comment: {str(e)}")
                    break
            
            # If we get here, all retries failed or an unexpected error occurred
            logger.warning("Using fallback comment generator")
            with cache_lock:
                api_stats['fallbacks_used'] += 1
            
            fallback = AIFallbackGenerator.generate_comment(tweet_text)
            return self.truncate_to_char_limit(fallback, max_length)
                
        except Exception as e:
            logger.error(f"Error generating comment: {str(e)}")
            
            with cache_lock:
                api_stats['fallbacks_used'] += 1
            
            return self.truncate_to_char_limit(AIFallbackGenerator.generate_comment(tweet_text), max_length)
    
    def generate_dm(
        self, 
        username: str, 
        context: str, 
        max_length: int = TWITTER_CHAR_LIMIT,
        use_cache: bool = False  # Default to False for DMs to ensure personalization
    ) -> str:
        """
        Generate a personalized DM for a user.
        
        Args:
            username: Twitter username
            context: Context for the DM
            max_length: Maximum length of the DM
            use_cache: Whether to use cached responses
            
        Returns:
            str: Generated DM text
        """
        logger.info(f"Generating DM for user @{username} with context: {context[:30]}...")
        
        # For DMs, we typically want each one to be unique, but allow caching if specified
        if use_cache:
            cached = self._get_cached_response('dm', username=username, context=context)
            if cached:
                logger.info(f"Using cached DM ({len(cached)} chars)")
                return self.truncate_to_char_limit(cached, max_length)
        
        try:
            if not username:
                username = "there"
            
            # Create a prompt for OpenAI
            prompt = (
             f"Write a friendly, personalized Twitter DM to @{username}.\n"
             f"Context about our project: {context}\n\n"
             "This message should:\n"
             "- Sound like it's from one person to another, not from a company\n"
             "- Be conversational and casual (use contractions, simple language)\n"
             "- Mention our comic art project in a way that feels natural, not promotional\n"
             "- Start with a genuine, personalized greeting\n"
             "- Avoid sounding templated or mass-produced\n"
             "- Keep it under 280 characters\n"
             "\nMost importantly: write as if you're messaging a friend about something cool, not selling a product."
          )
            
            logger.debug(f"DM prompt: {prompt[:100]}...")
            
            # Track retry attempts
            for attempt in range(MAX_RETRIES):
                try:
                    with cache_lock:
                        api_stats['calls'] += 1
                    
                    start_time = time.time()
                    response = self.client.chat.completions.create(
                        model=self.default_model,
                        messages=[
                            {"role": "system", "content": "You are a friendly artist reaching out to someone with similar interests. Your messages sound personal and conversational."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.8,
                        max_tokens=50
                    )
                    elapsed = time.time() - start_time
                    
                    dm_text = response.choices[0].message.content.strip()
                    
                    # Validate the response
                    valid, reason = AIResponseValidator.validate_dm(dm_text, max_length)
                    if not valid:
                        logger.warning(f"Generated invalid DM: {reason}. Retrying...")
                        continue
                    
                    # Update stats
                    with cache_lock:
                        api_stats['successes'] += 1
                    
                    # Cache the response if requested (usually not for DMs)
                    if use_cache:
                        self._cache_response('dm', dm_text, username=username, context=context)
                    
                    logger.info(f"Generated DM for @{username} ({len(dm_text)} chars) in {elapsed:.2f}s: {dm_text[:30]}...")
                    return self.truncate_to_char_limit(dm_text, max_length)
                    
                except openai.RateLimitError as e:
                    with cache_lock:
                        api_stats['failures'] += 1
                    
                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Rate limit hit, retrying in {wait_time} seconds: {str(e)}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Rate limit error after {MAX_RETRIES} attempts: {str(e)}")
                        break
                except openai.APIError as e:
                    with cache_lock:
                        api_stats['failures'] += 1
                    
                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"API error, retrying in {wait_time} seconds: {str(e)}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"API error after {MAX_RETRIES} attempts: {str(e)}")
                        break
                except Exception as e:
                    with cache_lock:
                        api_stats['failures'] += 1
                    
                    logger.error(f"Unexpected error generating DM: {str(e)}")
                    break
            
            # If we get here, all retries failed or an unexpected error occurred
            logger.warning("Using fallback DM generator")
            with cache_lock:
                api_stats['fallbacks_used'] += 1
            
            fallback = AIFallbackGenerator.generate_dm(username, context)
            return self.truncate_to_char_limit(fallback, max_length)
                
        except Exception as e:
            logger.error(f"Error generating DM: {str(e)}")
            
            with cache_lock:
                api_stats['fallbacks_used'] += 1
            
            return self.truncate_to_char_limit(f"Hi {username}, thanks for your support! See our comic art on Kickstarter!", max_length)
    
    def analyze_image(self, image_path: str) -> Optional[str]:
        """
        Analyze an image and return a description.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Optional[str]: Description of the image or None if error
        """
        logger.info(f"Analyzing image: {image_path}")
        
        try:
            # Check if the file exists
            if not os.path.exists(image_path):
                logger.error(f"Image file not found: {image_path}")
                # Return a fallback description without making an API call
                return "An exciting piece of comic book art from our Kickstarter campaign."
                
            # Log file info
            file_size = os.path.getsize(image_path) / 1024  # KB
            logger.debug(f"Image file size: {file_size:.2f} KB")
            
            # Read the image
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            # Track retry attempts
            for attempt in range(MAX_RETRIES):
                try:
                    with cache_lock:
                        api_stats['calls'] += 1
                    
                    logger.debug(f"Sending image to vision model (attempt {attempt+1}/{MAX_RETRIES})")
                    start_time = time.time()
                    
                    response = self.client.chat.completions.create(
                        model=self.vision_model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Describe this comic book art in 2-3 sentences, focusing on the style, characters, and mood."},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{base64_image}"
                                        }
                                    }
                                ]
                            }
                        ],
                        max_tokens=100,
                        temperature=0.7
                    )
                    
                    elapsed = time.time() - start_time
                    
                    # Update stats
                    with cache_lock:
                        api_stats['successes'] += 1
                    
                    description = response.choices[0].message.content.strip()
                    logger.info(f"Generated image description ({len(description)} chars) in {elapsed:.2f}s: {description[:50]}...")
                    return description
                    
                except openai.RateLimitError as e:
                    with cache_lock:
                        api_stats['failures'] += 1
                    
                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Rate limit hit, retrying in {wait_time} seconds: {str(e)}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Rate limit error after {MAX_RETRIES} attempts: {str(e)}")
                        break
                except openai.APIError as e:
                    with cache_lock:
                        api_stats['failures'] += 1
                    
                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"API error, retrying in {wait_time} seconds: {str(e)}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"API error after {MAX_RETRIES} attempts: {str(e)}")
                        break
                except Exception as e:
                    with cache_lock:
                        api_stats['failures'] += 1
                    
                    logger.error(f"Unexpected error analyzing image: {str(e)}")
                    break
            
            # If we get here, all retries failed or an unexpected error occurred
            logger.warning("Image analysis failed, returning generic description")
            with cache_lock:
                api_stats['fallbacks_used'] += 1
            
            return "An exciting piece of comic book art from our Kickstarter campaign."
                
        except Exception as e:
            logger.error(f"Error analyzing image: {str(e)}")
            
            with cache_lock:
                api_stats['fallbacks_used'] += 1
            
            return "An exciting piece of comic book art from our Kickstarter campaign."
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the AI integration.
        
        Returns:
            Dict[str, Any]: Status information
        """
        # Test API connection (but don't call during tests)
        api_available = True
        if os.getenv('TESTING') != 'true':
            api_available = self._test_api_connection()
        
        # Clean cache and get stats
        removed_entries = self._clean_cache()
        cache_size = len(response_cache)
        
        # Get API stats
        with cache_lock:
            stats = api_stats.copy()
        
        return {
            'api_available': api_available,
            'default_model': self.default_model,
            'vision_model': self.vision_model,
            'cache': {
                'size': cache_size,
                'removed_entries': removed_entries,
                'expiry_hours': self.cache_expiry
            },
            'performance': {
                'api_calls': stats['calls'],
                'successes': stats['successes'],
                'failures': stats['failures'],
                'cache_hits': stats['cache_hits'],
                'cache_misses': stats['cache_misses'],
                'fallbacks_used': stats['fallbacks_used'],
                'success_rate': f"{(stats['successes'] / stats['calls'] * 100):.1f}%" if stats['calls'] > 0 else "N/A",
                'cache_hit_rate': f"{(stats['cache_hits'] / (stats['cache_hits'] + stats['cache_misses']) * 100):.1f}%" if (stats['cache_hits'] + stats['cache_misses']) > 0 else "N/A"
            }
        }


# Alias for backward compatibility and easier imports
AIIntegration = OpenAIIntegration

# Example usage for testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='AI Integration Operations')
    parser.add_argument('--tweet', action='store_true', help='Test tweet generation')
    parser.add_argument('--comment', action='store_true', help='Test comment generation')
    parser.add_argument('--dm', action='store_true', help='Test DM generation')
    parser.add_argument('--image', type=str, help='Test image analysis with the given image path')
    parser.add_argument('--all', action='store_true', help='Test all functionality')
    parser.add_argument('--status', action='store_true', help='Show AI integration status')
    
    args = parser.parse_args()
    
    try:
        ai = OpenAIIntegration()
        
        if args.status or args.all:
            print("AI Integration Status:")
            status = ai.get_status()
            print(json.dumps(status, indent=2))
        
        if args.tweet or args.all:
            desc = "Image file: example.jpg"
            summ = "A dramatic scene in a dark, industrial underground setting with hints of futuristic technology."
            caption = ai.generate_tweet_text("example.jpg", summ)
            print(f"\nGenerated Tweet Caption ({len(caption)} chars):")
            print(caption)
        
        if args.comment or args.all:
            tweet_example = "Our new Kickstarter project is launching soon! Stay tuned for exclusive updates."
            comment = ai.generate_comment(tweet_example)
            print(f"\nGenerated Comment ({len(comment)} chars):")
            print(comment)
        
        if args.dm or args.all:
            dm_context = "Our campaign features limited edition prints of sci-fi comic art."
            dm = ai.generate_dm("testuser", dm_context)
            print(f"\nGenerated DM ({len(dm)} chars):")
            print(dm)
        
        if args.image:
            if os.path.exists(args.image):
                description = ai.analyze_image(args.image)
                print(f"\nImage Analysis for {args.image}:")
                print(description)
            else:
                print(f"\nError: Image file not found: {args.image}")
        
        # If no args provided, show usage
        if not any([args.tweet, args.comment, args.dm, args.image, args.all, args.status]):
            parser.print_help()
        
        # Show performance stats at the end
        if any([args.tweet, args.comment, args.dm, args.image, args.all]):
            print("\nPerformance Statistics:")
            stats = ai.get_status()['performance']
            print(f"Total API calls: {stats['api_calls']}")
            print(f"Success rate: {stats['success_rate']}")
            print(f"Cache hit rate: {stats['cache_hit_rate']}")
            print(f"Fallbacks used: {stats['fallbacks_used']}")
    
    except Exception as e:
        print(f"Error: {str(e)}")