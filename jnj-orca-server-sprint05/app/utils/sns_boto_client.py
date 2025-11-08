import boto3
import os
from app.config.settings import settings
import json
from datetime import datetime


# Need to Move this to settings or environment variable
TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:itx-bca-sce-dev-message-bus"


def get_sns_client():
    """
    Create and return an SNS client using AWS credentials from settings.

    Returns:
        boto3.client: A configured SNS client.
    """
    
    session = boto3.session.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.region,
    )
    sns_client = session.client("sns")
    return sns_client
    


def send_audit_log(log_data: list):
    """
    Publish a list of audit log entries to an AWS SNS topic.

    Args:
        log_data (list): A list of dictionaries, each representing an audit log entry.

    Returns:
        list: A list of SNS publish responses.

    Raises:
        ValueError: If log_data is not a list.
    """
    if not isinstance(log_data, list):
        raise ValueError("log_data must be a list of audit log entries.")

    sns = get_sns_client()
    response = sns.publish(
        TopicArn=TOPIC_ARN,
        Message=json.dumps(log_data)
    )
    return response