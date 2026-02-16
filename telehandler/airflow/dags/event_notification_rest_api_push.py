from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import requests

def push_rest_api_call(**kwargs):
    event = kwargs.get('event', {})
    url = 'https://example.com/api/endpoint'  # Replace with your API endpoint
    payload = {'event': event}
    response = requests.post(url, json=payload)
    print(f"Status: {response.status_code}, Response: {response.text}")

with DAG(
    dag_id='event_notification_rest_api_push',
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,  # Triggered by event, not scheduled
    catchup=False,
    tags=['event', 'rest_api'],
) as dag:
    push_api = PythonOperator(
        task_id='push_rest_api_call',
        python_callable=push_rest_api_call,
        provide_context=True,
    )

# To trigger this DAG with an event, use Airflow's TriggerDagRunOperator or an external trigger with event payload.
