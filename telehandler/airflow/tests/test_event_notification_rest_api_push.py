import unittest
from unittest.mock import patch, MagicMock
from airflow.dags.event_notification_rest_api_push import push_rest_api_call

class TestPushRestApiCall(unittest.TestCase):
    @patch('requests.post')
    def test_push_rest_api_call_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = 'Success'
        mock_post.return_value = mock_response

        event = {'type': 'test', 'data': 'sample'}
        push_rest_api_call(event=event)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn('json', kwargs)
        self.assertEqual(kwargs['json'], {'event': event})
        self.assertEqual(mock_response.status_code, 200)
        self.assertEqual(mock_response.text, 'Success')

    @patch('requests.post')
    def test_push_rest_api_call_failure(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'
        mock_post.return_value = mock_response

        event = {'type': 'test', 'data': 'sample'}
        push_rest_api_call(event=event)
        mock_post.assert_called_once()
        self.assertEqual(mock_response.status_code, 500)
        self.assertEqual(mock_response.text, 'Internal Server Error')

if __name__ == '__main__':
    unittest.main()
