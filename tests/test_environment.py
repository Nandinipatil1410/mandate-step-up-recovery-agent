from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mandate_recovery.environment import load_project_environment
from mandate_recovery.integrations import RazorpayTestGateway


class EnvironmentTests(unittest.TestCase):
    def test_dotenv_loads_without_overwriting_host_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "GROQ_API_KEY=file-value\nRAZORPAY_KEY_ID=rzp_test_from_file\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"GROQ_API_KEY": "host-value"}, clear=True):
                self.assertTrue(load_project_environment(root))
                self.assertEqual("host-value", os.environ["GROQ_API_KEY"])
                self.assertEqual("rzp_test_from_file", os.environ["RAZORPAY_KEY_ID"])

    def test_payment_link_collection_count_is_bounded_before_network(self) -> None:
        gateway = RazorpayTestGateway(
            key_id="rzp_test_example", key_secret="not-a-real-secret"
        )
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            gateway.fetch_payment_links(count=0)


if __name__ == "__main__":
    unittest.main()
