import os
from flask import Flask, render_template_string, jsonify, request
import logging
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Attr

# Configure logging
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    logger.warning("FLASK_SECRET_KEY not set in .env. Using default (insecure for production).")
    app.secret_key = "defaultsecretkey"

# Table names from environment or defaults
TARGETED_USERS_TABLE = os.getenv("DYNAMODB_TARGETED_USERS_TABLE", "TargetedUsers")
KEYWORDS_TABLE = os.getenv("DYNAMODB_KEYWORDS_TABLE", "Keywords")

# DynamoDB configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", os.getenv("AWS_ACCESS_KEY"))
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal types to numbers for JSON"""
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o) if o % 1 else int(o)
        return super(DecimalEncoder, self).default(o)


def get_dynamodb_resource():
    """Get a boto3 DynamoDB resource with credentials"""
    return boto3.resource(
        'dynamodb',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )


def count_items(table_name):
    """Count the number of items in a DynamoDB table"""
    try:
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table(table_name)
        response = table.scan(
            Select='COUNT'
        )
        count = response.get('Count', 0)
        logger.debug(f"Counted {count} items in table {table_name}")
        return count
    except Exception as e:
        logger.error(f"Error counting items in table {table_name}: {str(e)}")
        return 0


def get_table_items(table_name, limit=100, filter_expression=None):
    """Get items from a DynamoDB table with pagination and optional filtering"""
    try:
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table(table_name)
        
        scan_kwargs = {
            'Limit': limit
        }
        
        if filter_expression:
            scan_kwargs['FilterExpression'] = filter_expression
            
        response = table.scan(**scan_kwargs)
        items = response.get('Items', [])
        
        logger.debug(f"Retrieved {len(items)} items from table {table_name}")
        return items
    except Exception as e:
        logger.error(f"Error getting items from table {table_name}: {str(e)}")
        return []


def get_engagement_stats():
    """Calculate comprehensive engagement statistics"""
    try:
        dynamodb = get_dynamodb_resource()
        
        # Get users with engagement data for user-focused stats
        users_table = dynamodb.Table(TARGETED_USERS_TABLE)
        users_response = users_table.scan()
        users = users_response.get('Items', [])
        
        # Get keywords table for engagement attempts
        keywords_table = dynamodb.Table(KEYWORDS_TABLE)
        
        # Get all tweets marked as "Engaged"
        engaged_response = keywords_table.scan(
            FilterExpression=Attr('Engaged').eq(True)
        )
        engaged_items = engaged_response.get('Items', [])
        
        # Count different engagement types from user records
        likes = 0
        retweets = 0
        comments = 0
        dms = 0
        
        # Track users who received engagements
        engaged_users = set()
        
        for user in users:
            engagements = user.get('Engagements', {})
            if engagements:
                user_likes = engagements.get('Likes', 0)
                user_retweets = engagements.get('Retweets', 0) 
                user_comments = engagements.get('Comments', 0)
                user_dms = engagements.get('DMs', 0)
                
                likes += user_likes
                retweets += user_retweets
                comments += user_comments
                dms += user_dms
                
                # Track unique users who received any engagement
                if user_likes + user_retweets + user_comments + user_dms > 0:
                    engaged_users.add(user.get('UserID', user.get('Username', '')))
        
        # Count engagement attempts vs successes from tweet data
        total_attempts = len(engaged_items)
        successful_attempts = 0
        
        # Count by engagement type
        like_attempts = 0
        like_successes = 0
        retweet_attempts = 0
        retweet_successes = 0
        comment_attempts = 0
        comment_successes = 0
        dm_attempts = 0
        dm_successes = 0
        
        # Analyze engagement records
        for item in engaged_items:
            # Check if item has engagement status data
            if 'EngagementStatus' in item:
                statuses = item.get('EngagementStatus', {})
                
                # Count attempts and successes by type
                if 'LikeAttempted' in statuses:
                    like_attempts += 1
                    if statuses.get('LikeSucceeded', False):
                        like_successes += 1
                        successful_attempts += 1
                
                if 'RetweetAttempted' in statuses:
                    retweet_attempts += 1
                    if statuses.get('RetweetSucceeded', False):
                        retweet_successes += 1
                        successful_attempts += 1
                
                if 'CommentAttempted' in statuses:
                    comment_attempts += 1
                    if statuses.get('CommentSucceeded', False):
                        comment_successes += 1
                        successful_attempts += 1
            else:
                # If no detailed status, count everything as an attempt
                # (legacy data structure)
                successful_attempts += 1  # Assume success for backward compatibility
        
        # Get DM stats
        dm_attempts = sum(1 for user in users if 'DMAttempted' in user)
        dm_successes = sum(1 for user in users if user.get('DMSent', False))
        
        # Calculate total attempts (include DMs)
        total_attempts += dm_attempts
        successful_attempts += dm_successes
        
        # Calculate success rates (avoid division by zero)
        like_success_rate = like_successes / like_attempts if like_attempts > 0 else 0
        retweet_success_rate = retweet_successes / retweet_attempts if retweet_attempts > 0 else 0
        comment_success_rate = comment_successes / comment_attempts if comment_attempts > 0 else 0
        dm_success_rate = dm_successes / dm_attempts if dm_attempts > 0 else 0
        
        # Calculate overall success rate
        overall_success_rate = successful_attempts / total_attempts if total_attempts > 0 else 0
        
        # Get recent engagement timeline (last 7 days)
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)
        
        # Return comprehensive engagement statistics
        stats = {
            # Basic counts from user records
            'likes': likes,
            'retweets': retweets,
            'comments': comments,
            'dms': dms,
            'total': likes + retweets + comments + dms,
            
            # Attempt vs success metrics
            'attempts': {
                'likes': like_attempts,
                'retweets': retweet_attempts,
                'comments': comment_attempts,
                'dms': dm_attempts,
                'total': total_attempts
            },
            'successes': {
                'likes': like_successes,
                'retweets': retweet_successes,
                'comments': comment_successes,
                'dms': dm_successes,
                'total': successful_attempts
            },
            'success_rates': {
                'likes': like_success_rate,
                'retweets': retweet_success_rate,
                'comments': comment_success_rate,
                'dms': dm_success_rate,
                'overall': overall_success_rate
            },
            
            # User metrics
            'engaged_users_count': len(engaged_users),
            'users_with_engagement_data': len([u for u in users if 'Engagements' in u])
        }
        
        logger.info(f"Calculated engagement stats: {likes} likes, {retweets} retweets, {comments} comments, {dms} DMs")
        return stats
    except Exception as e:
        logger.error(f"Error getting engagement stats: {str(e)}")
        return {
            'likes': 0, 'retweets': 0, 'comments': 0, 'dms': 0, 'total': 0,
            'attempts': {'likes': 0, 'retweets': 0, 'comments': 0, 'dms': 0, 'total': 0},
            'successes': {'likes': 0, 'retweets': 0, 'comments': 0, 'dms': 0, 'total': 0},
            'success_rates': {'likes': 0, 'retweets': 0, 'comments': 0, 'dms': 0, 'overall': 0},
            'engaged_users_count': 0,
            'users_with_engagement_data': 0
        }

def get_activity_timeline(days=7):
    """Generate activity timeline data for the past N days"""
    try:
        # Get data from DynamoDB
        dynamodb = get_dynamodb_resource()
        users_table = dynamodb.Table(TARGETED_USERS_TABLE)
        keywords_table = dynamodb.Table(KEYWORDS_TABLE)
        
        # Calculate date range
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        # Initialize data structure for timeline
        timeline = {}
        for i in range(days):
            date = (end_date - timedelta(days=i)).strftime('%Y-%m-%d')
            timeline[date] = {'users': 0, 'keywords': 0, 'engagements': 0}
        
        # Scan users table for DateAdded
        users_response = users_table.scan()
        for user in users_response.get('Items', []):
            if 'DateAdded' in user:
                try:
                    date_added = datetime.fromisoformat(user['DateAdded'].replace('Z', '+00:00'))
                    if start_date <= date_added <= end_date:
                        date_key = date_added.strftime('%Y-%m-%d')
                        if date_key in timeline:
                            timeline[date_key]['users'] += 1
                except (ValueError, TypeError):
                    continue
        
        # Scan keywords table for FoundAt/Timestamp
        keywords_response = keywords_table.scan()
        for keyword in keywords_response.get('Items', []):
            timestamp_field = keyword.get('Timestamp', keyword.get('FoundAt'))
            if timestamp_field:
                try:
                    timestamp = datetime.fromisoformat(timestamp_field.replace('Z', '+00:00'))
                    if start_date <= timestamp <= end_date:
                        date_key = timestamp.strftime('%Y-%m-%d')
                        if date_key in timeline:
                            timeline[date_key]['keywords'] += 1
                except (ValueError, TypeError):
                    continue
            
            # Look for engagements
            if keyword.get('Engaged', False) and 'EngagedAt' in keyword:
                try:
                    engaged_at = datetime.fromisoformat(keyword['EngagedAt'].replace('Z', '+00:00'))
                    if start_date <= engaged_at <= end_date:
                        date_key = engaged_at.strftime('%Y-%m-%d')
                        if date_key in timeline:
                            timeline[date_key]['engagements'] += 1
                except (ValueError, TypeError):
                    continue
        
        # Format for chart.js
        labels = list(timeline.keys())
        users_data = [timeline[date]['users'] for date in labels]
        keywords_data = [timeline[date]['keywords'] for date in labels]
        engagement_data = [timeline[date]['engagements'] for date in labels]
        
        logger.debug(f"Generated activity timeline for {days} days with {sum(users_data)} users, {sum(keywords_data)} keywords, {sum(engagement_data)} engagements")
        return {
            'labels': labels,
            'users_data': users_data,
            'keywords_data': keywords_data,
            'engagement_data': engagement_data
        }
    except Exception as e:
        logger.error(f"Error generating activity timeline: {str(e)}")
        return {'labels': [], 'users_data': [], 'keywords_data': [], 'engagement_data': []}


def get_tweet_history(limit=50):
    """
    Get history of tweets posted by the bot
    
    Args:
        limit: Maximum number of tweets to retrieve
        
    Returns:
        List of tweet data in chronological order
    """
    try:
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table(TARGETED_USERS_TABLE)
        
        # Scan for content history items
        response = table.scan(
            FilterExpression=Attr('Type').eq('ContentHistory'),
            Limit=limit
        )
        
        tweets = response.get('Items', [])
        
        # Sort by timestamp, newest first
        tweets.sort(key=lambda x: x.get('Timestamp', ''), reverse=True)
        
        logger.debug(f"Retrieved {len(tweets)} tweets from tweet history")
        return tweets
    except Exception as e:
        logger.error(f"Error getting tweet history: {str(e)}")
        return []


def get_dm_history(limit=50):
    """
    Get history of DMs sent by the bot
    
    Args:
        limit: Maximum number of DMs to retrieve
        
    Returns:
        List of DM data in chronological order
    """
    try:
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table(TARGETED_USERS_TABLE)
        
        # Scan for users who have been sent DMs
        response = table.scan(
            FilterExpression=Attr('DMSent').eq(True),
            Limit=limit
        )
        
        dms = response.get('Items', [])
        
        # Sort by DMSentAt, newest first
        dms.sort(key=lambda x: x.get('DMSentAt', ''), reverse=True)
        
        logger.debug(f"Retrieved {len(dms)} DMs from DM history")
        return dms
    except Exception as e:
        logger.error(f"Error getting DM history: {str(e)}")
        return []


def get_engagement_history(limit=50):
    """
    Get history of engagement activities (likes, retweets, comments)
    
    Args:
        limit: Maximum number of engagements to retrieve
        
    Returns:
        List of engagement data in chronological order
    """
    try:
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table(KEYWORDS_TABLE)
        
        # Scan for keywords with engagement data
        response = table.scan(
            FilterExpression=Attr('Engaged').eq(True),
            Limit=limit
        )
        
        engagements = response.get('Items', [])
        
        # Sort by EngagedAt, newest first
        engagements.sort(key=lambda x: x.get('EngagedAt', ''), reverse=True)
        
        logger.debug(f"Retrieved {len(engagements)} records from engagement history")
        return engagements
    except Exception as e:
        logger.error(f"Error getting engagement history: {str(e)}")
        return []


def get_target_hashtags():
    """Get the list of hashtags the bot is targeting"""
    hashtags_str = os.getenv('TARGET_HASHTAGS', 'Kickstarter,crowdfunding,indiegame,tabletopgame')
    return [tag.strip() for tag in hashtags_str.split(',')]


def get_target_keywords():
    """Get the list of keywords the bot is targeting"""
    keywords_str = os.getenv('TARGET_KEYWORDS', 'Kickstarter campaign,board game,crowdfunding')
    return [keyword.strip() for keyword in keywords_str.split(',')]


def get_bot_rates():
    """Get the bot's rate limits for different actions"""
    return {
        'likes_per_hour': int(os.getenv('MAX_LIKES_PER_HOUR', 15)),
        'retweets_per_hour': int(os.getenv('MAX_RETWEETS_PER_HOUR', 8)),
        'comments_per_hour': int(os.getenv('MAX_COMMENTS_PER_HOUR', 5)),
        'dms_per_hour': int(os.getenv('MAX_DMS_PER_HOUR', 2)),
        'dms_per_day': int(os.getenv('MAX_DMS_PER_DAY', 5)),
        'tweets_per_hour': int(os.getenv('MAX_TWEETS_PER_HOUR', 1))
    }


def get_system_status():
    """Get the system status (uptime, last run times, etc.)"""
    try:
        # For now, just return a basic status
        # This could be enhanced with more data from DynamoDB or logs
        return {
            'system_time': datetime.now(timezone.utc).isoformat(),
            'dynamodb_connected': True,
            'tables': {
                'users': TARGETED_USERS_TABLE,
                'keywords': KEYWORDS_TABLE
            },
            'region': AWS_REGION
        }
    except Exception as e:
        logger.error(f"Error getting system status: {str(e)}")
        return {
            'system_time': datetime.now(timezone.utc).isoformat(),
            'error': str(e)
        }


@app.route("/")
def dashboard():
    """Render the Twitter Bot activity dashboard."""
    try:
        # Get basic stats
        targeted_users_count = count_items(TARGETED_USERS_TABLE)
        keywords_count = count_items(KEYWORDS_TABLE)
        
        # Get configuration data
        target_hashtags = get_target_hashtags()
        target_keywords = get_target_keywords()
        bot_rates = get_bot_rates()
        system_status = get_system_status()
        
        # Get engagement stats
        engagement_stats = get_engagement_stats()
        
        # Get activity timeline
        timeline_data = get_activity_timeline(7)
        
        # Get activity history
        tweet_history = get_tweet_history(10)  # Only get 10 most recent for initial page load
        dm_history = get_dm_history(10)
        engagement_history = get_engagement_history(10)
        
        # Calculate percentages for donut chart
        total = targeted_users_count + keywords_count
        targeted_percent = (targeted_users_count / total * 100) if total > 0 else 0
        keywords_percent = (keywords_count / total * 100) if total > 0 else 0
        
        # Format timestamp
        formatted_timestamp = datetime.now(timezone.utc).strftime("%B %d, %Y %I:%M %p UTC")
        
        logger.info(f"Dashboard rendered: Users={targeted_users_count}, Keywords={keywords_count}, Engagements={engagement_stats['total']}")
        
        return render_template_string(
            DASHBOARD_TEMPLATE,
            timestamp=formatted_timestamp,
            targeted_users_count=targeted_users_count,
            keywords_count=keywords_count,
            total=total,
            target_hashtags=target_hashtags,
            target_keywords=target_keywords,
            bot_rates=bot_rates,
            system_status=system_status,
            engagement_stats=engagement_stats,
            timeline_data=timeline_data,
            tweet_history=tweet_history,
            dm_history=dm_history,
            engagement_history=engagement_history,
            year=datetime.now(timezone.utc).year
        )
    except Exception as e:
        logger.error(f"Error rendering dashboard: {str(e)}")
        return render_template_string(
            ERROR_TEMPLATE,
            error_message=f"Unable to render dashboard: {str(e)}"
        ), 500


@app.route("/api/users")
def get_users():
    """API endpoint to get targeted users data"""
    try:
        items = get_table_items(TARGETED_USERS_TABLE)
        # Convert any Decimal objects to regular numbers for JSON
        return json.dumps({"users": items}, cls=DecimalEncoder)
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/keywords")
def get_keywords():
    """API endpoint to get keywords data"""
    try:
        items = get_table_items(KEYWORDS_TABLE)
        # Convert any Decimal objects to regular numbers for JSON
        return json.dumps({"keywords": items}, cls=DecimalEncoder)
    except Exception as e:
        logger.error(f"Error fetching keywords: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats")
def get_stats():
    """API endpoint to get overall statistics"""
    try:
        # Get basic counts
        users_count = count_items(TARGETED_USERS_TABLE)
        keywords_count = count_items(KEYWORDS_TABLE)
        
        # Get engagement stats
        engagement_stats = get_engagement_stats()
        
        # Get timeline data
        days = request.args.get('days', 7, type=int)
        timeline_data = get_activity_timeline(days)
        
        return jsonify({
            "users_count": users_count,
            "keywords_count": keywords_count,
            "engagement_stats": engagement_stats,
            "timeline_data": timeline_data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        logger.error(f"Error fetching stats: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tweets")
def get_tweets():
    """API endpoint to get tweet history data"""
    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        # Get all tweets
        items = get_tweet_history(limit + offset)
        
        # Apply offset
        items = items[offset:offset + limit] if offset < len(items) else []
        
        # Convert any Decimal objects to regular numbers for JSON
        return json.dumps({"tweets": items}, cls=DecimalEncoder)
    except Exception as e:
        logger.error(f"Error fetching tweets: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/dms")
def get_dms():
    """API endpoint to get DM history data"""
    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        # Get all DMs
        items = get_dm_history(limit + offset)
        
        # Apply offset
        items = items[offset:offset + limit] if offset < len(items) else []
        
        # Convert any Decimal objects to regular numbers for JSON
        return json.dumps({"dms": items}, cls=DecimalEncoder)
    except Exception as e:
        logger.error(f"Error fetching DMs: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/engagements")
def get_engagements():
    """API endpoint to get engagement history data"""
    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        # Get all engagements
        items = get_engagement_history(limit + offset)
        
        # Apply offset
        items = items[offset:offset + limit] if offset < len(items) else []
        
        # Convert any Decimal objects to regular numbers for JSON
        return json.dumps({"engagements": items}, cls=DecimalEncoder)
    except Exception as e:
        logger.error(f"Error fetching engagements: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/refresh")
def refresh_data():
    """API endpoint to force refresh all dashboard data"""
    try:
        # Get basic stats
        targeted_users_count = count_items(TARGETED_USERS_TABLE)
        keywords_count = count_items(KEYWORDS_TABLE)
        
        # Get engagement stats
        engagement_stats = get_engagement_stats()
        
        # Get activity timeline
        days = request.args.get('days', 7, type=int)
        timeline_data = get_activity_timeline(days)
        
        # Get fresh activity history
        tweet_history = get_tweet_history(10)
        dm_history = get_dm_history(10)
        engagement_history = get_engagement_history(10)
        
        logger.info(f"Dashboard data refreshed via API: Users={targeted_users_count}, Keywords={keywords_count}, Engagements={engagement_stats['total']}")
        
        return jsonify({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "users_count": targeted_users_count,
            "keywords_count": keywords_count,
            "engagement_stats": engagement_stats,
            "timeline_data": timeline_data,
            "tweet_history": tweet_history,
            "dm_history": dm_history,
            "engagement_history": engagement_history
        })
    except Exception as e:
        logger.error(f"Error refreshing dashboard data: {str(e)}")
        return jsonify({"error": str(e)}), 500


ERROR_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Twitter Bot Dashboard - Error</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  </head>
  <body>
    <div class="container mt-5">
      <div class="alert alert-danger" role="alert">
        <h4 class="alert-heading">Error</h4>
        <p>{{ error_message }}</p>
      </div>
    </div>
  </body>
</html>
"""

DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Twitter Bot Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
      body {
        background-color: #F5F7F8;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      }
      .navbar {
        margin-bottom: 30px;
        background-color: #37474F !important;
      }
      .card {
        margin-bottom: 20px;
        border: none;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        transition: transform 0.3s ease;
      }
      .card:hover {
        transform: translateY(-5px);
      }
      .card-clickable {
        cursor: pointer;
      }
      footer {
        text-align: center;
        padding: 15px;
        background-color: #37474F;
        color: #fff;
        position: fixed;
        bottom: 0;
        width: 100%;
        z-index: 100;
      }
      .chart-container {
        position: relative;
        margin: auto;
        height: 300px;
      }
      .stats-header {
        color: #37474F;
        margin-bottom: 30px;
      }
      .bg-primary-custom {
        background-color: #40C4FF !important;
        color: white;
      }
      .bg-success-custom {
        background-color: #78909C !important;
        color: white;
      }
      .bg-info-custom {
        background-color: #80D8FF !important;
        color: #37474F;
      }
      .bg-warning-custom {
        background-color: #37474F !important;
        color: white;
      }
      .modal-header {
        background-color: #40C4FF;
        color: white;
      }
      .table-header {
        background-color: #78909C;
        color: white;
      }
      .refresh-btn {
        color: #40C4FF;
        cursor: pointer;
      }
      .nav-tabs .nav-link {
        color: #37474F;
      }
      .nav-tabs .nav-link.active {
        color: white;
        background-color: #40C4FF;
        border-color: #40C4FF;
      }
      .activity-container {
        margin-bottom: 60px;
      }
      .tweet-card, .dm-card, .engagement-card {
        margin-bottom: 15px;
        transition: all 0.2s ease;
      }
      .tweet-card:hover, .dm-card:hover, .engagement-card:hover {
        box-shadow: 0 6px 10px rgba(0,0,0,0.15);
      }
      .tweet-header, .dm-header, .engagement-header {
        display: flex;
        justify-content: space-between;
        padding: 10px 15px;
        color: white;
      }
      .tweet-header {
        background-color: #40C4FF;
      }
      .dm-header {
        background-color: #78909C;
      }
      .engagement-header {
        background-color: #80D8FF;
        color: #37474F;
      }
      .badge-custom {
        background-color: #37474F;
        color: white;
      }
      .pagination-custom .page-link {
        color: #40C4FF;
      }
      .pagination-custom .page-item.active .page-link {
        background-color: #40C4FF;
        border-color: #40C4FF;
        color: white;
      }
      .tab-content {
        padding-top: 20px;
      }
      .load-more-btn {
        background-color: #40C4FF;
        border-color: #40C4FF;
        color: white;
        margin-top: 10px;
      }
      .load-more-btn:hover {
        background-color: #37474F;
        border-color: #37474F;
      }
      .activity-date {
        font-size: 0.9rem;
        opacity: 0.8;
      }
      .activity-summary {
        margin-bottom: 30px;
      }
      .timestamp {
        font-size: 0.8rem;
        color: #78909C;
      }
      .view-more-link {
        color: #40C4FF;
        text-decoration: none;
      }
      .auto-refresh-toggle {
        color: white;
        margin-right: 20px;
      }
      .config-section {
        background-color: #f0f4f7;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 20px;
      }
      .hashtag-pill, .keyword-pill {
        background-color: #40C4FF;
        color: white;
        border-radius: 20px;
        padding: 5px 10px;
        margin: 3px;
        display: inline-block;
        font-size: 0.9rem;
      }
      .keyword-pill {
        background-color: #78909C;
      }
      .status-indicator {
        width: 12px;
        height: 12px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 5px;
      }
      .status-green {
        background-color: #4CAF50;
      }
      .status-red {
        background-color: #F44336;
      }
      .status-yellow {
        background-color: #FFC107;
      }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-dark">
      <div class="container">
        <a class="navbar-brand" href="#">
          <i class="fab fa-twitter me-2"></i>
          Twitter Bot Dashboard
        </a>
        <div class="d-flex align-items-center">
          <div class="form-check form-switch auto-refresh-toggle">
            <input class="form-check-input" type="checkbox" id="autoRefreshToggle">
            <label class="form-check-label text-white" for="autoRefreshToggle">
              Auto-refresh
            </label>
          </div>
          <span id="refresh-timer" class="badge bg-light text-dark me-2" style="display: none;">60s</span>
        </div>
      </div>
    </nav>

    <div class="container mb-5 pb-5">
      <div class="d-flex justify-content-between align-items-center mb-4">
        <h1 class="stats-header">
          <i class="fas fa-chart-line me-2"></i>
          Activity Dashboard
        </h1>
        <div>
          <p class="text-muted">
            <span id="last-updated">Last updated: {{ timestamp }}</span>
            <i class="fas fa-sync-alt ms-2 refresh-btn" onclick="refreshDashboardData()" title="Refresh dashboard"></i>
          </p>
        </div>
      </div>

      <div class="row">
        <!-- Targeted Users Card -->
        <div class="col-md-6 col-lg-3">
          <div class="card card-clickable bg-primary-custom" onclick="showUsersModal()">
            <div class="card-body text-center p-4">
              <h1 class="display-4" id="targeted-users-count">{{ targeted_users_count }}</h1>
              <h5 class="card-title">
                <i class="fas fa-users me-2"></i>
                Targeted Users
              </h5>
              <p class="card-text">Click to view details</p>
            </div>
          </div>
        </div>

        <!-- Keywords Card -->
        <div class="col-md-6 col-lg-3">
          <div class="card card-clickable bg-success-custom" onclick="showKeywordsModal()">
            <div class="card-body text-center p-4">
              <h1 class="display-4" id="keywords-count">{{ keywords_count }}</h1>
              <h5 class="card-title">
                <i class="fas fa-key me-2"></i>
                Keywords Stored
              </h5>
              <p class="card-text">Click to view details</p>
            </div>
          </div>
        </div>

        <!-- Engagement Card -->
        <div class="col-md-6 col-lg-3">
          <div class="card card-clickable bg-info-custom" onclick="showEngagementModal()">
            <div class="card-body text-center p-4">
              <h1 class="display-4" id="total-engagements">{{ engagement_stats.total }}</h1>
              <h5 class="card-title">
                <i class="fas fa-handshake me-2"></i>
                Total Engagements
              </h5>
              <p class="card-text">Click to view breakdown</p>
            </div>
          </div>
        </div>

        <!-- Success Rate Card -->
        <div class="col-md-6 col-lg-3">
          <div class="card bg-warning-custom">
            <div class="card-body text-center p-4">
              <h1 class="display-4">{{ "%.1f"|format(engagement_stats.total / targeted_users_count if targeted_users_count > 0 else 0) }}</h1>
              <h5 class="card-title">
                <i class="fas fa-chart-pie me-2"></i>
                Engagements per User
              </h5>
              <p class="card-text">Average engagement ratio</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Configuration Section -->
      <div class="row mt-4">
        <div class="col-md-12">
          <div class="card">
            <div class="card-header">
              <i class="fas fa-cog me-2"></i>
              Bot Configuration
            </div>
            <div class="card-body">
              <div class="row">
                <div class="col-md-6">
                  <div class="config-section">
                    <h6><i class="fas fa-hashtag me-2"></i>Target Hashtags</h6>
                    <div>
                      {% for hashtag in target_hashtags %}
                        <span class="hashtag-pill">#{{ hashtag }}</span>
                      {% endfor %}
                    </div>
                  </div>
                </div>
                <div class="col-md-6">
                  <div class="config-section">
                    <h6><i class="fas fa-key me-2"></i>Target Keywords</h6>
                    <div>
                      {% for keyword in target_keywords %}
                        <span class="keyword-pill">{{ keyword }}</span>
                      {% endfor %}
                    </div>
                  </div>
                </div>
              </div>
              <div class="row mt-3">
                <div class="col-md-6">
                  <div class="config-section">
                    <h6><i class="fas fa-tachometer-alt me-2"></i>Rate Limits</h6>
                    <div class="row">
                      <div class="col-6">
                        <p><i class="fas fa-heart me-1"></i> {{ bot_rates.likes_per_hour }}/hour</p>
                        <p><i class="fas fa-retweet me-1"></i> {{ bot_rates.retweets_per_hour }}/hour</p>
                      </div>
                      <div class="col-6">
                        <p><i class="fas fa-comment me-1"></i> {{ bot_rates.comments_per_hour }}/hour</p>
                        <p><i class="fas fa-envelope me-1"></i> {{ bot_rates.dms_per_hour }}/hour</p>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="col-md-6">
                  <div class="config-section">
                    <h6><i class="fas fa-server me-2"></i>System Status</h6>
                    <p>
                      <span class="status-indicator status-green"></span> DynamoDB Connection: OK
                    </p>
                    <p>
                      <span class="status-indicator status-green"></span> Region: {{ system_status.region }}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="row mt-4">
        <!-- Data Distribution Chart -->
        <div class="col-md-5">
          <div class="card">
            <div class="card-header">
              <i class="fas fa-chart-pie me-2"></i>
              Data Distribution
            </div>
            <div class="card-body">
              <div class="chart-container" style="height: 300px;">
                <canvas id="donutChart"></canvas>
              </div>
            </div>
          </div>
        </div>

        <!-- Engagement Breakdown Chart -->
        <div class="col-md-7">
          <div class="card">
            <div class="card-header">
              <i class="fas fa-chart-bar me-2"></i>
              Engagement Breakdown
            </div>
            <div class="card-body">
              <div class="chart-container" style="height: 300px;">
                <canvas id="engagementChart"></canvas>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="row mt-4">
        <!-- Activity Timeline Chart -->
        <div class="col-md-12">
          <div class="card">
            <div class="card-header">
              <i class="fas fa-calendar-alt me-2"></i>
              Activity Timeline (Last 7 Days)
            </div>
            <div class="card-body">
              <div class="chart-container" style="height: 300px;">
                <canvas id="timelineChart"></canvas>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Activity History Section -->
      <div class="row mt-4 activity-container">
        <div class="col-md-12">
          <div class="card">
            <div class="card-header">
              <i class="fas fa-history me-2"></i>
              Activity History
            </div>
            <div class="card-body">
              <ul class="nav nav-tabs" id="activityTabs" role="tablist">
                <li class="nav-item" role="presentation">
                  <button class="nav-link active" id="tweets-tab" data-bs-toggle="tab" data-bs-target="#tweets" type="button" role="tab">
                    <i class="fas fa-comment-dots me-2"></i>Tweets
                  </button>
                </li>
                <li class="nav-item" role="presentation">
                  <button class="nav-link" id="dms-tab" data-bs-toggle="tab" data-bs-target="#dms" type="button" role="tab">
                    <i class="fas fa-envelope me-2"></i>DMs
                  </button>
                </li>
                <li class="nav-item" role="presentation">
                  <button class="nav-link" id="engagements-tab" data-bs-toggle="tab" data-bs-target="#engagements" type="button" role="tab">
                    <i class="fas fa-handshake me-2"></i>Engagements
                  </button>
                </li>
              </ul>
              
              <div class="tab-content" id="activityTabContent">
                <!-- Tweets Tab -->
                <div class="tab-pane fade show active" id="tweets" role="tabpanel">
                  <div class="activity-summary">
                    <h5>Tweet History</h5>
                    <p class="text-muted">Recent tweets posted by your bot with media and engagement statistics.</p>
                  </div>
                  
                  <div id="tweetsList">
                    {% if tweet_history %}
                      {% for tweet in tweet_history %}
                        <div class="card tweet-card">
                          <div class="tweet-header">
                            <div>
                              <i class="fas fa-comment-dots me-2"></i>
                              Tweet ID: {{ tweet.TweetID }}
                            </div>
                            <div class="activity-date">
                              {{ tweet.Timestamp if tweet.Timestamp else "N/A" }}
                            </div>
                          </div>
                          <div class="card-body">
                            <div class="row">
                              <div class="col-md-3">
                                <div class="text-center">
                                  <img src="/api/placeholder/150/150" alt="Content Image" class="img-fluid rounded">
                                  <p class="small mt-2">Content ID: {{ tweet.ContentID }}</p>
                                </div>
                              </div>
                              <div class="col-md-9">
                                <div class="mb-3">
                                  <h6>Tweet Text:</h6>
                                  <p>"This is a placeholder for the tweet text. The actual text would be stored and displayed here."</p>
                                </div>
                                <div class="d-flex justify-content-between">
                                  <div>
                                    <span class="badge bg-primary-custom me-2">
                                      <i class="fas fa-heart me-1"></i> 0
                                    </span>
                                    <span class="badge bg-success-custom me-2">
                                      <i class="fas fa-retweet me-1"></i> 0
                                    </span>
                                    <span class="badge bg-info-custom">
                                      <i class="fas fa-reply me-1"></i> 0
                                    </span>
                                  </div>
                                  <div>
                                    <a href="https://twitter.com/twitter/status/{{ tweet.TweetID }}" target="_blank" class="view-more-link">
                                      <i class="fas fa-external-link-alt me-1"></i>
                                      View on Twitter
                                    </a>
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      {% endfor %}
                    {% else %}
                      <div class="alert alert-info">
                        <i class="fas fa-info-circle me-2"></i>
                        No tweet history found. Once your bot posts tweets, they will appear here.
                      </div>
                    {% endif %}
                  </div>
                  
                  <div class="text-center mt-3">
                    <button id="loadMoreTweets" class="btn load-more-btn" {% if not tweet_history %}disabled{% endif %}>
                      <i class="fas fa-sync me-2"></i>Load More Tweets
                    </button>
                  </div>
                </div>
                
                <!-- DMs Tab -->
                <div class="tab-pane fade" id="dms" role="tabpanel">
                  <div class="activity-summary">
                    <h5>Direct Message History</h5>
                    <p class="text-muted">Recent direct messages sent to users by your bot.</p>
                  </div>
                  
                  <div id="dmsList">
                    {% if dm_history %}
                      {% for dm in dm_history %}
                        <div class="card dm-card">
                          <div class="dm-header">
                            <div>
                              <i class="fas fa-envelope me-2"></i>
                              DM to @{{ dm.Username }}
                            </div>
                            <div class="activity-date">
                              {{ dm.DMSentAt if dm.DMSentAt else "N/A" }}
                            </div>
                          </div>
                          <div class="card-body">
                            <div class="row">
                              <div class="col-md-2">
                                <div class="text-center">
                                  <i class="fas fa-user-circle fa-4x" style="color: #78909C;"></i>
                                  <p class="mt-2">UserID: {{ dm.UserID }}</p>
                                </div>
                              </div>
                              <div class="col-md-10">
                                <div class="mb-3">
                                  <h6>Message Content:</h6>
                                  <p>"This is a placeholder for the DM content. The actual message would be stored and displayed here."</p>
                                </div>
                                <div class="d-flex justify-content-between">
                                  <div>
                                    <span class="badge badge-custom me-2">
                                      <i class="fas fa-check-circle me-1"></i> Sent
                                    </span>
                                    {% if dm.get('DMResponse', False) %}
                                      <span class="badge bg-success-custom">
                                        <i class="fas fa-reply me-1"></i> Received Reply
                                      </span>
                                    {% endif %}
                                  </div>
                                  <div>
                                    <span class="timestamp">Followers: {{ dm.FollowerCount if dm.FollowerCount else "unknown" }}</span>
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      {% endfor %}
                    {% else %}
                      <div class="alert alert-info">
                        <i class="fas fa-info-circle me-2"></i>
                        No DM history found. Once your bot sends DMs, they will appear here.
                      </div>
                    {% endif %}
                  </div>
                  
                  <div class="text-center mt-3">
                    <button id="loadMoreDMs" class="btn load-more-btn" {% if not dm_history %}disabled{% endif %}>
                      <i class="fas fa-sync me-2"></i>Load More DMs
                    </button>
                  </div>
                </div>
                
                <!-- Engagements Tab -->
                <div class="tab-pane fade" id="engagements" role="tabpanel">
                  <div class="activity-summary">
                    <h5>Engagement History</h5>
                    <p class="text-muted">Recent likes, retweets, and comments performed by your bot.</p>
                  </div>
                  
                  <div id="engagementsList">
                    {% if engagement_history %}
                      {% for engagement in engagement_history %}
                        <div class="card engagement-card">
                          <div class="engagement-header">
                            <div>
                              <i class="fas fa-handshake me-2"></i>
                              Engaged with @{{ engagement.Username }}'s Tweet
                            </div>
                            <div class="activity-date">
                              {{ engagement.EngagedAt if engagement.EngagedAt else "N/A" }}
                            </div>
                          </div>
                          <div class="card-body">
                            <div class="row">
                              <div class="col-md-12">
                                <div class="mb-3">
                                  <h6>Tweet Content:</h6>
                                  <p>"{{ engagement.TweetText if engagement.TweetText else 'No tweet text available' }}"</p>
                                </div>
                                <div class="d-flex justify-content-between">
                                  <div>
                                    <span class="badge bg-primary-custom me-2">
                                      <i class="fas fa-heart me-1"></i> Liked
                                    </span>
                                    <span class="badge bg-success-custom me-2">
                                      <i class="fas fa-retweet me-1"></i> Retweeted
                                    </span>
                                    <span class="badge bg-info-custom">
                                      <i class="fas fa-reply me-1"></i> Commented
                                    </span>
                                  </div>
                                  <div>
                                    <a href="https://twitter.com/twitter/status/{{ engagement.TweetID }}" target="_blank" class="view-more-link">
                                      <i class="fas fa-external-link-alt me-1"></i>
                                      View on Twitter
                                    </a>
                                  </div>
                                </div>
                                <div class="mt-3">
                                  <h6>Matching Keyword:</h6>
                                  <span class="badge bg-warning-custom">{{ engagement.Keyword }}</span>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      {% endfor %}
                    {% else %}
                      <div class="alert alert-info">
                        <i class="fas fa-info-circle me-2"></i>
                        No engagement history found. Once your bot engages with users, it will appear here.
                      </div>
                    {% endif %}
                  </div>
                  
                  <div class="text-center mt-3">
                    <button id="loadMoreEngagements" class="btn load-more-btn" {% if not engagement_history %}disabled{% endif %}>
                      <i class="fas fa-sync me-2"></i>Load More Engagements
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Users Modal -->
    <div class="modal fade" id="usersModal" tabindex="-1" aria-labelledby="usersModalLabel" aria-hidden="true">
      <div class="modal-dialog modal-xl">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="usersModalLabel">
              <i class="fas fa-users me-2"></i>
              Targeted Users
            </h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="text-center mb-3" id="usersLoading">
              <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
              </div>
              <p>Loading users data...</p>
            </div>
            <div id="usersTable" style="display: none;">
              <input type="text" class="form-control mb-3" id="userSearch" placeholder="Search users...">
              <div class="table-responsive">
                <table class="table table-striped table-hover">
                  <thead class="table-header">
                    <tr>
                      <th>Username</th>
                      <th>Followers</th>
                      <th>Profile Age (days)</th>
                      <th>Tweet Count</th>
                      <th>Date Added</th>
                      <th>Hashtags</th>
                    </tr>
                  </thead>
                  <tbody id="usersTableBody">
                    <!-- Will be populated dynamically -->
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Keywords Modal -->
    <div class="modal fade" id="keywordsModal" tabindex="-1" aria-labelledby="keywordsModalLabel" aria-hidden="true">
      <div class="modal-dialog modal-xl">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="keywordsModalLabel">
              <i class="fas fa-key me-2"></i>
              Keywords Stored
            </h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="text-center mb-3" id="keywordsLoading">
              <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
              </div>
              <p>Loading keywords data...</p>
            </div>
            <div id="keywordsTable" style="display: none;">
              <input type="text" class="form-control mb-3" id="keywordSearch" placeholder="Search keywords...">
              <div class="table-responsive">
                <table class="table table-striped table-hover">
                  <thead class="table-header">
                    <tr>
                      <th>Keyword</th>
                      <th>Username</th>
                      <th>Tweet ID</th>
                      <th>Tweet Text</th>
                      <th>Found At</th>
                    </tr>
                  </thead>
                  <tbody id="keywordsTableBody">
                    <!-- Will be populated dynamically -->
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Engagement Modal -->
    <div class="modal fade" id="engagementModal" tabindex="-1" aria-labelledby="engagementModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="engagementModalLabel">
              <i class="fas fa-handshake me-2"></i>
              Engagement Breakdown
            </h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="table-responsive">
              <table class="table table-striped">
                <thead class="table-header">
                  <tr>
                    <th>Engagement Type</th>
                    <th>Count</th>
                    <th>Percentage</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><i class="fas fa-heart me-2"></i> Likes</td>
                    <td>{{ engagement_stats.likes }}</td>
                    <!-- Engagement Modal (continued) -->
                    <td>{{ "%.1f"|format(engagement_stats.likes / engagement_stats.total * 100 if engagement_stats.total > 0 else 0) }}%</td>
                  </tr>
                  <tr>
                    <td><i class="fas fa-retweet me-2"></i> Retweets</td>
                    <td>{{ engagement_stats.retweets }}</td>
                    <td>{{ "%.1f"|format(engagement_stats.retweets / engagement_stats.total * 100 if engagement_stats.total > 0 else 0) }}%</td>
                  </tr>
                  <tr>
                    <td><i class="fas fa-comment me-2"></i> Comments</td>
                    <td>{{ engagement_stats.comments }}</td>
                    <td>{{ "%.1f"|format(engagement_stats.comments / engagement_stats.total * 100 if engagement_stats.total > 0 else 0) }}%</td>
                  </tr>
                  <tr>
                    <td><i class="fas fa-envelope me-2"></i> DMs</td>
                    <td>{{ engagement_stats.dms }}</td>
                    <td>{{ "%.1f"|format(engagement_stats.dms / engagement_stats.total * 100 if engagement_stats.total > 0 else 0) }}%</td>
                  </tr>
                  <tr class="table-active">
                    <td><strong>Total</strong></td>
                    <td><strong>{{ engagement_stats.total }}</strong></td>
                    <td>100%</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
          </div>
        </div>
      </div>
    </div>

    <footer>
      © {{ year }} Twitter Bot Dashboard. All rights reserved.
    </footer>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
      // Data Distribution Chart
      const donutCtx = document.getElementById('donutChart').getContext('2d');
      const donutChart = new Chart(donutCtx, {
        type: 'doughnut',
        data: {
          labels: ['Targeted Users', 'Keywords'],
          datasets: [{
            data: [{{ targeted_users_count }}, {{ keywords_count }}],
            backgroundColor: ['#40C4FF', '#78909C'],
            borderWidth: 0
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom' },
            tooltip: {
              callbacks: {
                label: function(context) {
                  let label = context.label || '';
                  let value = context.raw;
                  let total = {{ total }};
                  let percentage = total ? ((value / total) * 100).toFixed(1) : 0;
                  return label + ': ' + value + ' (' + percentage + '%)';
                }
              }
            }
          }
        }
      });

      // Engagement Breakdown Chart
      const engagementCtx = document.getElementById('engagementChart').getContext('2d');
      const engagementChart = new Chart(engagementCtx, {
        type: 'bar',
        data: {
          labels: ['Likes', 'Retweets', 'Comments', 'DMs'],
          datasets: [{
            label: 'Count',
            data: [
              {{ engagement_stats.likes }},
              {{ engagement_stats.retweets }},
              {{ engagement_stats.comments }},
              {{ engagement_stats.dms }}
            ],
            backgroundColor: ['#40C4FF', '#80D8FF', '#78909C', '#37474F'],
            borderWidth: 0
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              beginAtZero: true,
              ticks: {
                precision: 0
              }
            }
          }
        }
      });

      // Activity Timeline Chart
      const timelineCtx = document.getElementById('timelineChart').getContext('2d');
      const timelineLabels = {{ timeline_data.labels|tojson }};
      const timelineChart = new Chart(timelineCtx, {
        type: 'line',
        data: {
          labels: timelineLabels,
          datasets: [
            {
              label: 'Users Added',
              data: {{ timeline_data.users_data|tojson }},
              borderColor: '#40C4FF',
              backgroundColor: 'rgba(64, 196, 255, 0.1)',
              borderWidth: 2,
              fill: true,
              tension: 0.4
            },
            {
              label: 'Keywords Found',
              data: {{ timeline_data.keywords_data|tojson }},
              borderColor: '#78909C',
              backgroundColor: 'rgba(120, 144, 156, 0.1)',
              borderWidth: 2,
              fill: true,
              tension: 0.4
            },
            {
              label: 'Engagements',
              data: {{ timeline_data.engagement_data|tojson if timeline_data.engagement_data else '[]' }},
              borderColor: '#FF7043',
              backgroundColor: 'rgba(255, 112, 67, 0.1)',
              borderWidth: 2,
              fill: true,
              tension: 0.4
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              beginAtZero: true,
              ticks: {
                precision: 0
              }
            }
          }
        }
      });

      // Functions to show modals and load data
      function showUsersModal() {
        const modal = new bootstrap.Modal(document.getElementById('usersModal'));
        modal.show();
        loadUsersData();
      }

      function showKeywordsModal() {
        const modal = new bootstrap.Modal(document.getElementById('keywordsModal'));
        modal.show();
        loadKeywordsData();
      }

      function showEngagementModal() {
        const modal = new bootstrap.Modal(document.getElementById('engagementModal'));
        modal.show();
      }

      // Function to load users data via AJAX
      function loadUsersData() {
        document.getElementById('usersLoading').style.display = 'block';
        document.getElementById('usersTable').style.display = 'none';
        
        fetch('/api/users')
          .then(response => response.json())
          .then(data => {
            const tableBody = document.getElementById('usersTableBody');
            tableBody.innerHTML = '';
            
            data.users.forEach(user => {
              const row = document.createElement('tr');
              
              // Format the date
              let dateAdded = 'N/A';
              if (user.DateAdded) {
                try {
                  const date = new Date(user.DateAdded);
                  dateAdded = date.toLocaleDateString('en-US', { 
                    year: 'numeric', 
                    month: 'short', 
                    day: 'numeric' 
                  });
                } catch (e) {
                  dateAdded = user.DateAdded;
                }
              }
              
              // Format hashtags
              const hashtags = user.HashtagsUsed ? user.HashtagsUsed.join(', ') : 'N/A';
              
              row.innerHTML = `
                <td>${user.Username || 'N/A'}</td>
                <td>${user.FollowerCount || 0}</td>
                <td>${user.ProfileAge || 0}</td>
                <td>${user.TweetCount || 0}</td>
                <td>${dateAdded}</td>
                <td>${hashtags}</td>
              `;
              
              tableBody.appendChild(row);
            });
            
            document.getElementById('usersLoading').style.display = 'none';
            document.getElementById('usersTable').style.display = 'block';
            
            // Initialize search functionality
            initializeSearch('userSearch', 'usersTableBody');
          })
          .catch(error => {
            console.error('Error fetching users data:', error);
            document.getElementById('usersLoading').innerHTML = 
              `<div class="alert alert-danger">Error loading data: ${error.message}</div>`;
          });
      }

      // Function to load keywords data via AJAX
      function loadKeywordsData() {
        document.getElementById('keywordsLoading').style.display = 'block';
        document.getElementById('keywordsTable').style.display = 'none';
        
        fetch('/api/keywords')
          .then(response => response.json())
          .then(data => {
            const tableBody = document.getElementById('keywordsTableBody');
            tableBody.innerHTML = '';
            
            data.keywords.forEach(keyword => {
              const row = document.createElement('tr');
              
              // Format the date
              let foundAt = 'N/A';
              const timestamp = keyword.Timestamp || keyword.FoundAt;
              if (timestamp) {
                try {
                  const date = new Date(timestamp);
                  foundAt = date.toLocaleDateString('en-US', { 
                    year: 'numeric', 
                    month: 'short', 
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                  });
                } catch (e) {
                  foundAt = timestamp;
                }
              }
              
              // Truncate tweet text
              let tweetText = keyword.TweetText || 'N/A';
              if (tweetText.length > 50) {
                tweetText = tweetText.substring(0, 50) + '...';
              }
              
              row.innerHTML = `
                <td>${keyword.Keyword || 'N/A'}</td>
                <td>${keyword.Username || 'N/A'}</td>
                <td><a href="https://twitter.com/twitter/status/${keyword.TweetID}" target="_blank">${keyword.TweetID || 'N/A'}</a></td>
                <td title="${keyword.TweetText || ''}">${tweetText}</td>
                <td>${foundAt}</td>
              `;
              
              tableBody.appendChild(row);
            });
            
            document.getElementById('keywordsLoading').style.display = 'none';
            document.getElementById('keywordsTable').style.display = 'block';
            
            // Initialize search functionality
            initializeSearch('keywordSearch', 'keywordsTableBody');
          })
          .catch(error => {
            console.error('Error fetching keywords data:', error);
            document.getElementById('keywordsLoading').innerHTML = 
              `<div class="alert alert-danger">Error loading data: ${error.message}</div>`;
          });
      }

      // Auto-refresh functionality
      let autoRefreshInterval = null;
      const REFRESH_INTERVAL = 60000; // 1 minute in milliseconds
      let remainingSeconds = 60;
      let timerInterval = null;

      function startAutoRefresh() {
        if (autoRefreshInterval) {
          clearInterval(autoRefreshInterval);
        }
        
        // Reset the timer display
        remainingSeconds = 60;
        updateTimerDisplay();
        
        // Show the timer display
        document.getElementById('refresh-timer').style.display = 'inline-block';
        
        // Start the countdown timer
        if (timerInterval) {
          clearInterval(timerInterval);
        }
        
        timerInterval = setInterval(() => {
          remainingSeconds--;
          updateTimerDisplay();
          
          if (remainingSeconds <= 0) {
            remainingSeconds = 60;
          }
        }, 1000);
        
        // Start the auto-refresh interval
        autoRefreshInterval = setInterval(() => {
          refreshDashboardData();
        }, REFRESH_INTERVAL);
        
        console.log(`Auto-refresh enabled. Will refresh every ${REFRESH_INTERVAL/1000} seconds`);
      }

      function stopAutoRefresh() {
        if (autoRefreshInterval) {
          clearInterval(autoRefreshInterval);
          autoRefreshInterval = null;
        }
        
        if (timerInterval) {
          clearInterval(timerInterval);
          timerInterval = null;
        }
        
        // Hide the timer display
        document.getElementById('refresh-timer').style.display = 'none';
        
        console.log('Auto-refresh disabled');
      }

      function updateTimerDisplay() {
        document.getElementById('refresh-timer').textContent = `${remainingSeconds}s`;
      }

      function refreshDashboardData() {
        document.getElementById('last-updated').innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Refreshing...`;
        
        fetch('/api/refresh')
          .then(response => response.json())
          .then(data => {
            // Update counters
            document.getElementById('targeted-users-count').textContent = data.users_count;
            document.getElementById('keywords-count').textContent = data.keywords_count;
            document.getElementById('total-engagements').textContent = data.engagement_stats.total;
            
            // Update timestamp
            document.getElementById('last-updated').textContent = 
                `Last updated: ${new Date(data.timestamp).toLocaleString()}`;
            
            // Update charts
            updateDonutChart(data.users_count, data.keywords_count);
            updateEngagementChart(data.engagement_stats);
            updateTimelineChart(data.timeline_data);
            
            // Update activity tabs if data is provided
            if (data.tweet_history && data.tweet_history.length > 0) updateTweetsList(data.tweet_history);
            if (data.dm_history && data.dm_history.length > 0) updateDMsList(data.dm_history);
            if (data.engagement_history && data.engagement_history.length > 0) updateEngagementsList(data.engagement_history);
            
            console.log('Dashboard data refreshed successfully');
          })
          .catch(error => {
            console.error('Error refreshing dashboard data:', error);
            document.getElementById('last-updated').textContent = `Last updated: Refresh failed`;
          });
      }

      // Functions to update charts
      function updateDonutChart(usersCount, keywordsCount) {
        if (donutChart) {
          donutChart.data.datasets[0].data = [usersCount, keywordsCount];
          donutChart.update();
        }
      }

      function updateEngagementChart(stats) {
        if (engagementChart) {
          engagementChart.data.datasets[0].data = [
            stats.likes,
            stats.retweets,
            stats.comments,
            stats.dms
          ];
          engagementChart.update();
        }
      }

      function updateTimelineChart(timelineData) {
        if (timelineChart) {
          timelineChart.data.labels = timelineData.labels;
          timelineChart.data.datasets[0].data = timelineData.users_data;
          timelineChart.data.datasets[1].data = timelineData.keywords_data;
          if (timelineData.engagement_data) {
            timelineChart.data.datasets[2].data = timelineData.engagement_data;
          }
          timelineChart.update();
        }
      }

      // Load More functionality for activity tabs
      document.getElementById('loadMoreTweets').addEventListener('click', function() {
        const tweetsList = document.getElementById('tweetsList');
        const button = this;
        button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...';
        button.disabled = true;
        
        // Get current number of tweets to use as offset
        const currentCount = tweetsList.querySelectorAll('.tweet-card').length;
        
        fetch(`/api/tweets?limit=10&offset=${currentCount}`)
          .then(response => response.json())
          .then(data => {
            if (data.tweets && data.tweets.length > 0) {
              // Add new tweets to the list
              data.tweets.forEach(tweet => {
                const tweetElement = document.createElement('div');
                tweetElement.className = 'card tweet-card';
                
                // Format timestamp
                let timestamp = tweet.Timestamp || 'N/A';
                
                tweetElement.innerHTML = `
                  <div class="tweet-header">
                    <div>
                      <i class="fas fa-comment-dots me-2"></i>
                      Tweet ID: ${tweet.TweetID}
                    </div>
                    <div class="activity-date">
                      ${timestamp}
                    </div>
                  </div>
                  <div class="card-body">
                    <div class="row">
                      <div class="col-md-3">
                        <div class="text-center">
                          <img src="/api/placeholder/150/150" alt="Content Image" class="img-fluid rounded">
                          <p class="small mt-2">Content ID: ${tweet.ContentID}</p>
                        </div>
                      </div>
                      <div class="col-md-9">
                        <div class="mb-3">
                          <h6>Tweet Text:</h6>
                          <p>"This is a placeholder for the tweet text. The actual text would be stored and displayed here."</p>
                        </div>
                        <div class="d-flex justify-content-between">
                          <div>
                            <span class="badge bg-primary-custom me-2">
                              <i class="fas fa-heart me-1"></i> 0
                            </span>
                            <span class="badge bg-success-custom me-2">
                              <i class="fas fa-retweet me-1"></i> 0
                            </span>
                            <span class="badge bg-info-custom">
                              <i class="fas fa-reply me-1"></i> 0
                            </span>
                          </div>
                          <div>
                            <a href="https://twitter.com/twitter/status/${tweet.TweetID}" target="_blank" class="view-more-link">
                              <i class="fas fa-external-link-alt me-1"></i>
                              View on Twitter
                            </a>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                `;
                
                tweetsList.appendChild(tweetElement);
              });
              
              button.innerHTML = '<i class="fas fa-sync me-2"></i>Load More Tweets';
              button.disabled = false;
              
              // If fewer than requested tweets were returned, disable the button
              if (data.tweets.length < 10) {
                button.disabled = true;
                button.innerHTML = 'No More Tweets';
              }
            } else {
              button.disabled = true;
              button.innerHTML = 'No More Tweets';
            }
          })
          .catch(error => {
            console.error('Error loading more tweets:', error);
            button.innerHTML = '<i class="fas fa-exclamation-circle me-2"></i>Error Loading Tweets';
            setTimeout(() => {
              button.innerHTML = '<i class="fas fa-sync me-2"></i>Try Again';
              button.disabled = false;
            }, 3000);
          });
      });
      
      document.getElementById('loadMoreDMs').addEventListener('click', function() {
        const dmsList = document.getElementById('dmsList');
        const button = this;
        button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...';
        button.disabled = true;
        
        // Get current number of DMs to use as offset
        const currentCount = dmsList.querySelectorAll('.dm-card').length;
        
        fetch(`/api/dms?limit=10&offset=${currentCount}`)
          .then(response => response.json())
          .then(data => {
            if (data.dms && data.dms.length > 0) {
              // Add new DMs to the list
              data.dms.forEach(dm => {
                const dmElement = document.createElement('div');
                dmElement.className = 'card dm-card';
                
                // Format timestamp
                let timestamp = dm.DMSentAt || 'N/A';
                
                dmElement.innerHTML = `
                  <div class="dm-header">
                    <div>
                      <i class="fas fa-envelope me-2"></i>
                      DM to @${dm.Username}
                    </div>
                    <div class="activity-date">
                      ${timestamp}
                    </div>
                  </div>
                  <div class="card-body">
                    <div class="row">
                      <div class="col-md-2">
                        <div class="text-center">
                          <i class="fas fa-user-circle fa-4x" style="color: #78909C;"></i>
                          <p class="mt-2">UserID: ${dm.UserID}</p>
                        </div>
                      </div>
                      <div class="col-md-10">
                        <div class="mb-3">
                          <h6>Message Content:</h6>
                          <p>"This is a placeholder for the DM content. The actual message would be stored and displayed here."</p>
                        </div>
                        <div class="d-flex justify-content-between">
                          <div>
                            <span class="badge badge-custom me-2">
                              <i class="fas fa-check-circle me-1"></i> Sent
                            </span>
                            ${dm.DMResponse ? 
                              `<span class="badge bg-success-custom">
                                <i class="fas fa-reply me-1"></i> Received Reply
                              </span>` : ''}
                          </div>
                          <div>
                            <span class="timestamp">Followers: ${dm.FollowerCount || 'unknown'}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                `;
                
                dmsList.appendChild(dmElement);
              });
              
              button.innerHTML = '<i class="fas fa-sync me-2"></i>Load More DMs';
              button.disabled = false;
              
              // If fewer than requested DMs were returned, disable the button
              if (data.dms.length < 10) {
                button.disabled = true;
                button.innerHTML = 'No More DMs';
              }
            } else {
              button.disabled = true;
              button.innerHTML = 'No More DMs';
            }
          })
          .catch(error => {
            console.error('Error loading more DMs:', error);
            button.innerHTML = '<i class="fas fa-exclamation-circle me-2"></i>Error Loading DMs';
            setTimeout(() => {
              button.innerHTML = '<i class="fas fa-sync me-2"></i>Try Again';
              button.disabled = false;
            }, 3000);
          });
      });
      
      document.getElementById('loadMoreEngagements').addEventListener('click', function() {
        const engagementsList = document.getElementById('engagementsList');
        const button = this;
        button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...';
        button.disabled = true;
        
        // Get current number of engagements to use as offset
        const currentCount = engagementsList.querySelectorAll('.engagement-card').length;
        
        fetch(`/api/engagements?limit=10&offset=${currentCount}`)
          .then(response => response.json())
          .then(data => {
            if (data.engagements && data.engagements.length > 0) {
              // Add new engagements to the list
              data.engagements.forEach(engagement => {
                const engagementElement = document.createElement('div');
                engagementElement.className = 'card engagement-card';
                
                // Format timestamp
                let timestamp = engagement.EngagedAt || 'N/A';
                
                engagementElement.innerHTML = `
                  <div class="engagement-header">
                    <div>
                      <i class="fas fa-handshake me-2"></i>
                      Engaged with @${engagement.Username}'s Tweet
                    </div>
                    <div class="activity-date">
                      ${timestamp}
                    </div>
                  </div>
                  <div class="card-body">
                    <div class="row">
                      <div class="col-md-12">
                        <div class="mb-3">
                          <h6>Tweet Content:</h6>
                          <p>"${engagement.TweetText || 'No tweet text available'}"</p>
                        </div>
                        <div class="d-flex justify-content-between">
                          <div>
                            <span class="badge bg-primary-custom me-2">
                              <i class="fas fa-heart me-1"></i> Liked
                            </span>
                            <span class="badge bg-success-custom me-2">
                              <i class="fas fa-retweet me-1"></i> Retweeted
                            </span>
                            <span class="badge bg-info-custom">
                              <i class="fas fa-reply me-1"></i> Commented
                            </span>
                          </div>
                          <div>
                            <a href="https://twitter.com/twitter/status/${engagement.TweetID}" target="_blank" class="view-more-link">
                              <i class="fas fa-external-link-alt me-1"></i>
                              View on Twitter
                            </a>
                          </div>
                        </div>
                        <div class="mt-3">
                          <h6>Matching Keyword:</h6>
                          <span class="badge bg-warning-custom">${engagement.Keyword}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                `;
                
                engagementsList.appendChild(engagementElement);
              });
              
              button.innerHTML = '<i class="fas fa-sync me-2"></i>Load More Engagements';
              button.disabled = false;
              
              // If fewer than requested engagements were returned, disable the button
              if (data.engagements.length < 10) {
                button.disabled = true;
                button.innerHTML = 'No More Engagements';
              }
            } else {
              button.disabled = true;
              button.innerHTML = 'No More Engagements';
            }
          })
          .catch(error => {
            console.error('Error loading more engagements:', error);
            button.innerHTML = '<i class="fas fa-exclamation-circle me-2"></i>Error Loading Engagements';
            setTimeout(() => {
              button.innerHTML = '<i class="fas fa-sync me-2"></i>Try Again';
              button.disabled = false;
            }, 3000);
          });
      });

      // Function to initialize search functionality for tables
      function initializeSearch(inputId, tableBodyId) {
        const searchInput = document.getElementById(inputId);
        const tableBody = document.getElementById(tableBodyId);
        const rows = tableBody.getElementsByTagName('tr');
        
        searchInput.addEventListener('keyup', function() {
          const term = searchInput.value.toLowerCase();
          
          for (let i = 0; i < rows.length; i++) {
            const row = rows[i];
            const text = row.textContent.toLowerCase();
            
            if (text.indexOf(term) > -1) {
              row.style.display = '';
            } else {
              row.style.display = 'none';
            }
          }
        });
      }

      // Initialize auto-refresh toggle
      document.getElementById('autoRefreshToggle').addEventListener('change', function() {
        if (this.checked) {
          startAutoRefresh();
        } else {
          stopAutoRefresh();
        }
      });

      // Initialize charts and data on page load
      document.addEventListener('DOMContentLoaded', function() {
        // Initialize tooltip
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
          return new bootstrap.Tooltip(tooltipTriggerEl);
        });
      });
    </script>
  </body>
</html>
"""

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", 5003))
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    app.run(debug=True, host=host, port=port)