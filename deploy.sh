#!/bin/bash
# deploy.sh

echo "Packaging application for Elastic Beanstalk..."
zip -r deployment-package.zip . -x "*.git*" -x "venv/*" -x "*.zip" -x "*.pem" -x "*.env"

echo "Deploying to Elastic Beanstalk..."
eb deploy

echo "Deployment complete!"