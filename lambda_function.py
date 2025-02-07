import json
import base64
import uuid
from config.config import ENDPOINT_NAME, PARAMETERS, OUTPUT_BUCKET_NAME
from config.prompt import *
from config.templates import get_input_data_json
from utils.logger import setup_logger
from handlers.s3_handler import save_result_to_s3, download_json_from_s3
from handlers.sagemaker_handler import SageMakerHandler
from handlers.dynamodb_handler import DynamoDBHandler
from utils.json_processor import process_json

logger = setup_logger()
dynamodb_handler = DynamoDBHandler()

def lambda_handler(event, context):
    logger.info('Received event: %s', json.dumps(event))

    try:
        body = parse_event(event)
        action = body.get('action', '')
        user_id = body.get('UserID', '')
        event_id = body.get('EventID', '')
        input_text = body.get('Input_text', '')

        if action == 'predict':
            return handle_predict(user_id, event_id, input_text)
        elif action == 'update':
            json_content = body.get('Json_content', '')
            return handle_clarification(user_id, event_id, input_text, json_content)
        elif action == 'test':
            return generate_response(200, {'message': 'ENDPOINT connection test successful'})
        else:
            return generate_response(400, {'error': f'Invalid action: {action}'})
    except Exception as e:
        logger.error('Error processing request: %s', str(e))
        return generate_response(505, {'error': 'Error processing request', 'details': str(e)})

def parse_event(event):
    body = base64.b64decode(event['body']).decode('utf-8')
    return json.loads(body)

def generate_response(status_code, body):
    return {
        'statusCode': status_code,
        'body': json.dumps(body)
    }

def predict(input_text, action):
    try:
        sagemaker_handler = SageMakerHandler(ENDPOINT_NAME)
    except Exception as e:
        logger.info("Endpoint connection error")
        generate_response(503, {'error': 'Sagemaker Endpoint Connection Error'})
        return None
    
    preset_prompts = {
        'predict': PRESET_PROMPT_1,
        'update': PRESET_PROMPT_2
    }

    preset_prompt = preset_prompts.get(action, PRESET_PROMPT_1)
    
    input_data_json = get_input_data_json(preset_prompt, input_text, PARAMETERS)
    try:
        result = sagemaker_handler.predict(input_data_json)
        logger.info('Result from prediction: %s', result)
    except Exception as e:
        logger.error(f"Error during prediction: {str(e)}")
        return generate_response(100, {'error': "prediction error in sagemaker_handler.predict(input_data_json)"})
    # processed_content = process_json(result)
    return result

def handle_predict(user_id, event_id, input_text):
    try:
        logger.info('predict text: %s', input_text)
        processed_content = predict(input_text, "predict")
        save_result_to_s3(user_id, event_id, processed_content)
        # save_result_to_dynamodb(user_id, event_id, processed_content)
        return generate_response(200, processed_content)
    except RuntimeError as e:
        logger.error(str(e))
        return generate_response(101, {'error': str(e)})
    
def handle_clarification(user_id, event_id, input_text, json_content):
    # s3_key = f"{user_id}/{event_id}.json"
    # current_content = download_json_from_s3(OUTPUT_BUCKET_NAME, s3_key)
    # current_content = json.dumps(current_content)

    combine_text = json.dumps({
        "user": input_text,
        "json": json_content
    })

    try:
        processed_content = predict(combine_text, "update")
        save_result_to_s3(user_id, event_id, processed_content)
        return generate_response(200, processed_content)
    except Exception as e:
        logger.error(f"Error during clarification: {str(e)}")
        return generate_response(400, {'error': str(e)})

def save_result_to_dynamodb(user_id, eventID, processed_content):
    try:
        dynamodb_handler.update_item(user_id, eventID, processed_content)
        logger.info('Saved result to DynamoDB for UserID: %s', user_id)
    except Exception as e:
        logger.error(f"Error saving to DynamoDB: {str(e)}")
        raise RuntimeError(f"Saving to DynamoDB failed: {str(e)}")