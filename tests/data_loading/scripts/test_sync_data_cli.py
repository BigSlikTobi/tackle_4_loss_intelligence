
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.functions.data_loading.scripts.sync_data_cli import main

class TestSyncDataCli(unittest.TestCase):
    def setUp(self):
        # Setup environment variables
        self.env_patcher = patch.dict(os.environ, {
            "SUPABASE_URL_DEV": "http://test-dev-url",
            "SUPABASE_KEY_DEV": "test-dev-key",
            "SUPABASE_URL": "http://test-prod-url",
            "SUPABASE_KEY": "test-prod-key"
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    @patch('src.functions.data_loading.scripts.sync_data_cli.get_supabase_client')
    @patch('src.functions.data_loading.scripts.sync_data_cli.setup_cli_logging')
    @patch('argparse.ArgumentParser.parse_args')
    def test_sync_basic_flow(self, mock_args, mock_logging, mock_get_client):
        # Mock CLI args
        mock_args.return_value = MagicMock(
            tables=['public.teams'],
            limit=10,
            wipe=False,
            all=False,
            dry_run=False,
            verbose=False
        )

        # Mock Supabase Clients
        mock_source_client = MagicMock()
        mock_target_client = MagicMock()
        # First call is source, second is target
        mock_get_client.side_effect = [mock_source_client, mock_target_client]

        # Mock Source Response
        mock_source_response = MagicMock()
        mock_source_response.data = [{'id': 1, 'name': 'Team A'}]
        
        # Mock .schema().table().select().order().range().execute() chain
        (mock_source_client.schema.return_value
            .table.return_value
            .select.return_value
            .order.return_value
            .range.return_value
            .execute.return_value) = mock_source_response

        # Execute
        main()

        # Verify Source Call
        mock_source_client.schema.assert_called_with('public')
        mock_source_client.schema.return_value.table.assert_called_with('teams')
        # Check order call
        mock_source_client.schema.return_value.table.return_value.select.return_value.order.assert_called_with("created_at", desc=True)
        
        # Verify Target Call (Upsert)
        mock_target_client.schema.assert_called_with('public')
        mock_target_client.schema.return_value.table.assert_called_with('teams')
        mock_target_client.schema.return_value.table.return_value.upsert.assert_called_once()
        
    @patch('src.functions.data_loading.scripts.sync_data_cli.get_supabase_client')
    @patch('src.functions.data_loading.scripts.sync_data_cli.setup_cli_logging')
    @patch('argparse.ArgumentParser.parse_args')
    def test_sync_pagination(self, mock_args, mock_logging, mock_get_client):
        # Mock CLI args with --all
        mock_args.return_value = MagicMock(
            tables=['teams'],
            limit=100,
            wipe=False,
            all=True,
            dry_run=False,
            verbose=False
        )
        
        mock_source_client = MagicMock()
        mock_target_client = MagicMock()
        mock_get_client.side_effect = [mock_source_client, mock_target_client]
        
        # Mock Pagination Response
        page1_data = [{'id': i} for i in range(1000)]
        page2_data = [{'id': i} for i in range(1000, 1500)]
        
        response1 = MagicMock()
        response1.data = page1_data
        response2 = MagicMock()
        response2.data = page2_data
        
        # Mock chain response side_effect
        # The chain is source_client.schema().table().select().order().range().execute()
        execute_mock = (mock_source_client.schema.return_value
            .table.return_value
            .select.return_value
            .order.return_value
            .range.return_value
            .execute)
            
        execute_mock.side_effect = [response1, response2]
        
        main()
        
        # Verify execute called twice
        self.assertEqual(execute_mock.call_count, 2)
        
        # Verify order called
        # mock_source_client.schema.return_value.table.return_value.select.return_value.order.assert_called_with("created_at", desc=True)


    @patch('src.functions.data_loading.scripts.sync_data_cli.get_supabase_client')
    @patch('src.functions.data_loading.scripts.sync_data_cli.setup_cli_logging')
    @patch('argparse.ArgumentParser.parse_args')
    def test_sync_resilience(self, mock_args, mock_logging, mock_get_client):
        # Mock CLI args
        mock_args.return_value = MagicMock(
            tables=['public.teams'],
            limit=10,
            wipe=False,
            all=False,
            dry_run=False,
            verbose=False
        )

        mock_source_client = MagicMock()
        mock_target_client = MagicMock()
        mock_get_client.side_effect = [mock_source_client, mock_target_client]

        # Source data: 3 records
        records = [{'id': 1}, {'id': 2}, {'id': 3}]
        mock_source_response = MagicMock()
        mock_source_response.data = records
        
        (mock_source_client.schema.return_value
            .table.return_value
            .select.return_value
            .order.return_value
            .range.return_value
            .execute.return_value) = mock_source_response

        # Target Upsert Behavior
        # 1. Batch upsert fails
        # 2. Individual upserts:
        #    - Record 1: Success
        #    - Record 2: Fail (e.g. FK violation)
        #    - Record 3: Success
        
        upsert_mock = mock_target_client.schema.return_value.table.return_value.upsert
        execute_mock = upsert_mock.return_value.execute
        
        # side_effect sequence:
        # 1. Batch call -> Raises Exception
        # 2. Individual call (rec 1) -> Success
        # 3. Individual call (rec 2) -> Raises Exception
        # 4. Individual call (rec 3) -> Success
        execute_mock.side_effect = [
            Exception("Batch FK Error"), 
            MagicMock(), 
            Exception("Row FK Error"), 
            MagicMock()
        ]

        main()

        # Verify:
        # - Batch attempted once
        # - Individual attempted 3 times
        # Total upsert calls = 4
        self.assertEqual(upsert_mock.call_count, 4)
        
        # Verify logging of errors (we can't easily check logs without more mocking, 
        # but execution without crash proves resilience)

if __name__ == '__main__':
    unittest.main()
