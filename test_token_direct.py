#!/usr/bin/env python3
"""
Comprehensive OAuth token diagnostic script.
"""

import os
import sys
import json
import logging
import requests
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("token_test")

# Load environment variables
load_dotenv()

def test_token_directly():
    """Test the OAuth token directly without going through TwitterAPI class."""
    try:
        # Get token from environment
        token = os.getenv('OAUTH_2_ACCESS_TOKEN')
        if not token:
            logger.error("No OAuth token found in environment")
            return False
        
        token_preview = f"{token[:5]}...{token[-5:]}"
        logger.info(f"Testing token directly: {token_preview}")
        
        # Create headers
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Try a simple API request
        url = "https://api.twitter.com/2/tweets/search/recent"
        params = {
            'query': 'test',
            'max_results': 10  # FIXED: Changed from 5 to 10 to meet Twitter API requirements
        }
        
        logger.info("Making direct API request...")
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        # Check result
        if response.status_code == 200:
            data = response.json()
            tweet_count = len(data.get('data', []))
            logger.info(f"Success! Found {tweet_count} tweets with direct token test")
            return True
        else:
            logger.error(f"Direct API request failed: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
    
    except Exception as e:
        logger.error(f"Direct token test failed: {str(e)}")
        return False

def main():
    """Run diagnostic tests on the OAuth token."""
    logger.info("Starting OAuth token diagnostic")
    
    # 1. Test the token directly
    direct_test = test_token_directly()
    logger.info(f"Direct token test: {'PASSED' if direct_test else 'FAILED'}")
    
    # Exit with success if direct test passed
    return direct_test

if __name__ == "__main__":
    result = main()
    sys.exit(0 if result else 1)