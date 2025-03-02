# AWS Deployment Guide for the Twitter Bot

This guide outlines the steps to deploy the Twitter Bot to AWS using either EC2 or ECS.

## Prerequisites

Before deployment, ensure you have:

1. AWS account with appropriate permissions
2. AWS CLI installed and configured
3. Docker installed locally
4. Valid Twitter API OAuth tokens
5. OpenAI API key

## Deployment Options

### Option 1: Amazon EC2 Deployment

#### 1. Set Up EC2 Instance

1. Launch an EC2 instance:

   - Amazon Linux 2 or Ubuntu Server 20.04
   - t3.small or larger instance type
   - At least 20GB of EBS storage

2. Configure security groups:

   - Allow SSH (port 22) from your IP address
   - Allow HTTP (port 80) and HTTPS (port 443) if using web dashboard
   - Allow port 5003 if exposing the dashboard directly

3. Install Docker on the EC2 instance:

   ```bash
   # For Amazon Linux 2
   sudo yum update -y
   sudo amazon-linux-extras install docker
   sudo service docker start
   sudo usermod -a -G docker ec2-user
   sudo systemctl enable docker

   # For Ubuntu
   sudo apt update
   sudo apt install -y docker.io
   sudo systemctl start docker
   sudo systemctl enable docker
   sudo usermod -a -G docker ubuntu
   ```

#### 2. Set Up Environment File

Create a `.env` file in your project directory with all required environment variables:

```bash
# OpenAI API
OPENAI_API_KEY=your_openai_api_key

# Twitter API v1.1 & v2 Credentials
TWITTER_API_KEY=your_twitter_api_key
TWITTER_API_SECRET=your_twitter_api_secret
TWITTER_ACCESS_TOKEN=your_twitter_access_token
TWITTER_ACCESS_SECRET=your_twitter_access_secret
TWITTER_BEARER_TOKEN=your_twitter_bearer_token

# Twitter OAuth 2.0 Credentials
OAUTH_2_ACCESS_TOKEN=your_oauth2_access_token
OAUTH_2_REFRESH_TOKEN=your_oauth2_refresh_token
TOKEN_EXPIRY=expiry_timestamp
TWITTER_USER_ID=your_twitter_user_id

# AWS Credentials
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_REGION=your_aws_region

# S3 Configuration
S3_BUCKET_NAME=your_s3_bucket
S3_CONTENT_FOLDER=content

# DynamoDB Tables
DYNAMODB_TARGETED_USERS_TABLE=TargetedUsers
DYNAMODB_KEYWORDS_TABLE=Keywords

# Bot Configuration
TARGET_HASHTAGS=Kickstarter,crowdfunding,indiegame,tabletopgame
TARGET_KEYWORDS=Kickstarter campaign,board game,crowdfunding,backing,funding goal
MIN_FOLLOWERS=50
MIN_PROFILE_AGE_DAYS=30
MIN_TWEET_COUNT=20
MAX_ENGAGEMENT_AGE_DAYS=7

# Scheduling
POSTING_INTERVAL_HOURS=24
ENGAGEMENT_INTERVAL_HOURS=6
DM_SCHEDULE=mon,thu
DM_HOUR=15

# Logging
LOG_LEVEL=INFO
MAIN_LOG_FILE=/app/logs/main.log
```

#### 3. Build and Deploy Docker Image

1. Build the Docker image locally:

   ```bash
   docker build -t twitter-bot:latest .
   ```

2. Transfer the image to EC2 instance:

   - Option 1: Push to ECR and pull on EC2
   - Option 2: Save and load the image directly:
     ```bash
     docker save twitter-bot:latest | gzip > twitter-bot.tar.gz
     scp -i your-key.pem twitter-bot.tar.gz ec2-user@your-instance-ip:~
     ssh -i your-key.pem ec2-user@your-instance-ip
     docker load < twitter-bot.tar.gz
     ```

3. Run the container on EC2:

   ```bash
   docker run -d \
     --name twitter-bot \
     --restart unless-stopped \
     -p 5003:5003 \
     --env-file .env \
     -v /path/to/local_content:/app/local_test_data \
     -v /path/to/logs:/app/logs \
     twitter-bot:latest
   ```

4. Set up CloudWatch logging (optional):

   ```bash
   sudo amazon-linux-extras install -y collectd
   sudo amazon-linux-extras install -y aws-kinesis-agent
   # Configure CloudWatch agent to collect Docker logs
   ```

5. Set up a cron job to ensure the container is running:
   ```bash
   crontab -e
   # Add the following line to check every 5 minutes
   */5 * * * * /usr/bin/docker ps | grep twitter-bot || /usr/bin/docker start twitter-bot
   ```

### Option 2: Amazon ECS Deployment

#### 1. Set Up Amazon ECR Repository

1. Create an ECR repository for your Docker image:

   ```bash
   aws ecr create-repository --repository-name twitter-bot
   ```

2. Build and push the Docker image:

   ```bash
   aws ecr get-login-password --region your-region | docker login --username AWS --password-stdin your-account-id.dkr.ecr.your-region.amazonaws.com

   docker build -t twitter-bot:latest .

   docker tag twitter-bot:latest your-account-id.dkr.ecr.your-region.amazonaws.com/twitter-bot:latest

   docker push your-account-id.dkr.ecr.your-region.amazonaws.com/twitter-bot:latest
   ```

#### 2. Set Up AWS Resources

1. Create an ECS cluster (if you don't have one already):

   ```bash
   aws ecs create-cluster --cluster-name twitter-bot-cluster
   ```

2. Create a Task Definition:

   - Use the AWS console or define a JSON file
   - Configure environment variables (or use AWS Secrets Manager)
   - Set appropriate CPU/memory limits
   - Configure volumes for persistent data if needed

3. Create an ECS service:
   ```bash
   aws ecs create-service \
     --cluster twitter-bot-cluster \
     --service-name twitter-bot-service \
     --task-definition twitter-bot:1 \
     --desired-count 1
   ```

### Option 3: AWS Elastic Beanstalk (Simpler Option)

1. Prepare your application:

   - Make sure your Dockerfile is in the root of your project
   - Create a `Dockerrun.aws.json` file to configure the container

2. Install the EB CLI:

   ```bash
   pip install awsebcli
   ```

3. Initialize and deploy:

   ```bash
   eb init -p docker twitter-bot
   eb create twitter-bot-env
   ```

4. Configure environment variables in the Elastic Beanstalk console.

## AWS Services Setup

### 1. S3 Bucket Setup

1. Create an S3 bucket for content:

   ```bash
   aws s3 mb s3://your-twitter-bot-bucket
   ```

2. Set up bucket structure:

   ```bash
   aws s3api put-object --bucket your-twitter-bot-bucket --key content/
   ```

3. Upload initial content:
   ```bash
   aws s3 cp local_test_data/ s3://your-twitter-bot-bucket/content/ --recursive
   ```

### 2. DynamoDB Tables Setup

1. Create the tables through the AWS console or using AWS CLI:

   ```bash
   # The tables will be created automatically by the bot if they don't exist
   # Alternatively, you can create them manually:

   aws dynamodb create-table \
     --table-name TargetedUsers \
     --attribute-definitions AttributeName=UserID,AttributeType=S \
     --key-schema AttributeName=UserID,KeyType=HASH \
     --billing-mode PAY_PER_REQUEST

   aws dynamodb create-table \
     --table-name Keywords \
     --attribute-definitions \
       AttributeName=Keyword,AttributeType=S \
       AttributeName=TweetID,AttributeType=S \
     --key-schema \
       AttributeName=Keyword,KeyType=HASH \
       AttributeName=TweetID,KeyType=RANGE \
     --billing-mode PAY_PER_REQUEST
   ```

### 3. CloudWatch Setup

1. Create CloudWatch alarms for monitoring:

   ```bash
   # Example: Create an alarm for DynamoDB throttled requests
   aws cloudwatch put-metric-alarm \
     --alarm-name DynamoDB-ThrottledRequests \
     --alarm-description "Alarm when DynamoDB requests are throttled" \
     --metric-name ThrottledRequests \
     --namespace AWS/DynamoDB \
     --statistic Sum \
     --period 300 \
     --threshold 10 \
     --comparison-operator GreaterThanThreshold \
     --dimensions Name=TableName,Value=TargetedUsers \
     --evaluation-periods 1 \
     --alarm-actions your-sns-topic-arn
   ```

2. Set up CloudWatch Logs:

   ```bash
   # Create a log group
   aws logs create-log-group --log-group-name /twitter-bot/logs

   # Create a log stream
   aws logs create-log-stream --log-group-name /twitter-bot/logs --log-stream-name main
   ```

## Initial Bot Setup

1. Run the OAuth flow to get tokens:

   ```bash
   # On your local machine
   python src/regenerate_oauth2_token.py --auth
   ```

2. Run the initial setup script:

   ```bash
   docker exec twitter-bot python -m src.setup --init-all
   ```

3. Verify the setup:
   ```bash
   docker exec twitter-bot python -m src.twitter_bot status
   ```

## Maintenance and Monitoring

1. Set up automated token refresh:

   ```bash
   # Create a Lambda function or CloudWatch Event to refresh tokens
   aws events put-rule \
     --name TwitterBotTokenRefresh \
     --schedule-expression "rate(12 hours)"

   aws events put-targets \
     --rule TwitterBotTokenRefresh \
     --targets "Id"="1","Arn"="your-lambda-arn"
   ```

2. Monitor logs:

   ```bash
   aws logs tail /twitter-bot/logs
   ```

3. Check container status:

   ```bash
   docker ps -a | grep twitter-bot
   ```

4. Review DynamoDB tables:

   ```bash
   aws dynamodb scan --table-name TargetedUsers --select COUNT
   aws dynamodb scan --table-name Keywords --select COUNT
   ```

5. Backup strategy:

   ```bash
   # Set up DynamoDB backups
   aws dynamodb create-backup --table-name TargetedUsers --backup-name TargetedUsers-Backup

   # Set up S3 bucket versioning
   aws s3api put-bucket-versioning --bucket your-twitter-bot-bucket --versioning-configuration Status=Enabled
   ```

## Troubleshooting

1. Check logs:

   ```bash
   docker logs twitter-bot
   ```

2. SSH into the container:

   ```bash
   docker exec -it twitter-bot /bin/bash
   ```

3. Run diagnostics:

   ```bash
   docker exec twitter-bot python -m src.diagnostics
   ```

4. Common issues:
   - OAuth token expiration: Run the token refresh script
   - DynamoDB throttling: Consider increasing capacity
   - S3 access issues: Check IAM permissions

This guide provides a foundation for deploying your Twitter Bot to AWS. Adjust as needed based on your specific requirements and AWS environment configuration.
