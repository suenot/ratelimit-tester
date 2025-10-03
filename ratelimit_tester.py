#!/usr/bin/env python3
"""
Universal Rate Limit Tester
Tests API rate limits for each proxy and manages proxy status automatically.
"""

import json
import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    protocol: str
    host: str
    port: str
    username: str
    password: str
    status: str
    interval_ms: int

    def to_string(self) -> str:
        """Convert back to config string format."""
        return f"{self.protocol}:{self.host}:{self.port}:{self.username}:{self.password}:{self.status}:{self.interval_ms}"

    def get_proxy_url(self) -> str:
        """Get formatted proxy URL for requests."""
        if self.username and self.password:
            return f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.protocol}://{self.host}:{self.port}"


class RateLimitTester:
    """Universal rate limit tester for any API with proxy rotation."""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.proxies = self._parse_proxies()
        self.session = requests.Session()
        self.start_time = time.time()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        with open(self.config_path, 'r') as f:
            return json.load(f)

    def _parse_proxies(self) -> List[ProxyConfig]:
        """Parse proxy strings into ProxyConfig objects."""
        proxies = []
        for proxy_str in self.config.get('proxies', []):
            parts = proxy_str.split(':')
            if len(parts) >= 7:
                proxies.append(ProxyConfig(
                    protocol=parts[0],
                    host=parts[1],
                    port=parts[2],
                    username=parts[3],
                    password=parts[4],
                    status=parts[5],
                    interval_ms=int(parts[6])
                ))
        return proxies

    def _save_config(self) -> None:
        """Save updated proxy configurations back to config file."""
        # Update proxies in config
        self.config['proxies'] = [p.to_string() for p in self.proxies]

        # Create backup
        backup_path = f"{self.config_path}.backup"
        if self.config_path.exists():
            import shutil
            shutil.copy2(self.config_path, backup_path)

        # Save updated config
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)

        logger.info(f"Config saved. Backup created at {backup_path}")

    def _build_request_params(self) -> Dict[str, Any]:
        """Build request parameters from config."""
        api_config = self.config['api']

        # Build full URL with params
        url = api_config['url']
        params = api_config.get('params', {})

        # Build headers
        headers = api_config.get('headers', {})

        # Get timeout
        timeout = api_config.get('timeout_ms', 10000) / 1000.0

        return {
            'url': url,
            'params': params,
            'headers': headers,
            'timeout': timeout,
            'method': api_config.get('method', 'GET')
        }

    def _check_response(self, response: requests.Response) -> tuple[bool, str]:
        """
        Check if response is valid according to validation rules.
        Returns (is_valid, reason)
        """
        validation = self.config['api']['validation']

        # Check status code
        if response.status_code != 200:
            if response.status_code == 429:
                return False, "ratelimit_error"
            return False, f"http_error_{response.status_code}"

        # Check for Cloudflare
        response_text = response.text.lower()
        for indicator in validation.get('cloudflare_indicators', []):
            if indicator.lower() in response_text:
                return False, "cloudflare_block"

        # Check for rate limit indicators in response
        for indicator in validation.get('ratelimit_indicators', []):
            if indicator.lower() in response_text:
                return False, "ratelimit_error"

        # Check success field in JSON response
        try:
            data = response.json()
            success_field = validation.get('success_field')
            success_value = validation.get('success_value')

            if success_field and success_field in data:
                if data[success_field] != success_value:
                    return False, "api_success_false"
        except:
            pass

        return True, "ok"

    def _format_time(self, ms: int) -> str:
        """Format milliseconds to human-readable format."""
        if ms < 1000:
            return f"{ms}ms"
        elif ms < 60000:
            seconds = ms / 1000
            return f"{seconds:.2f}s"
        elif ms < 3600000:
            minutes = ms / 60000
            seconds = (ms % 60000) / 1000
            return f"{int(minutes)}m {seconds:.2f}s"
        else:
            hours = ms / 3600000
            minutes = (ms % 3600000) / 60000
            return f"{hours:.2f}h"

    def _disable_proxy(self, proxy: ProxyConfig, reason: str) -> None:
        """Disable a proxy in the config."""
        proxy.status = "disabled"
        # Calculate time in milliseconds from start
        elapsed_ms = int((time.time() - self.start_time) * 1000)
        proxy.interval_ms = elapsed_ms
        formatted_time = self._format_time(elapsed_ms)
        logger.warning(f"🔴 DISABLED proxy {proxy.host}:{proxy.port} | Reason: {reason} | Lifetime: {formatted_time}")
        self._save_config()

    def test_proxy(self, proxy: ProxyConfig) -> Dict[str, Any]:
        """
        Test a single proxy with the configured API in infinite loop.
        Returns test results when proxy is disabled or interrupted.
        """
        if proxy.status != "enabled":
            return {
                'proxy': f"{proxy.host}:{proxy.port}",
                'status': 'skipped',
                'reason': f'proxy is {proxy.status}'
            }

        formatted_interval = self._format_time(proxy.interval_ms)
        logger.info(f"🔄 Starting infinite test | Proxy: {proxy.host}:{proxy.port} | Interval: {formatted_interval}")

        # Build request params
        req_params = self._build_request_params()

        # Setup proxy
        proxy_url = proxy.get_proxy_url()
        proxies = {
            'http': proxy_url,
            'https': proxy_url
        }

        success_count = 0
        fail_count = 0
        start_time = time.time()
        request_num = 0

        # Test in infinite loop until error
        try:
            while True:
                request_num += 1

                try:
                    if req_params['method'] == 'GET':
                        response = self.session.get(
                            req_params['url'],
                            params=req_params['params'],
                            headers=req_params['headers'],
                            proxies=proxies,
                            timeout=req_params['timeout']
                        )
                    else:
                        response = self.session.post(
                            req_params['url'],
                            json=req_params.get('params'),
                            headers=req_params['headers'],
                            proxies=proxies,
                            timeout=req_params['timeout']
                        )

                    is_valid, reason = self._check_response(response)

                    if is_valid:
                        success_count += 1
                        elapsed_time = self._format_time(int((time.time() - start_time) * 1000))
                        logger.info(f"✅ Request #{request_num} OK | Success: {success_count}, Fail: {fail_count} | Proxy: {proxy.host}:{proxy.port} | Runtime: {elapsed_time}")
                    else:
                        fail_count += 1
                        logger.error(f"❌ Request #{request_num} FAILED | Reason: {reason} | Proxy: {proxy.host}:{proxy.port}")

                        # Disable proxy immediately on any error
                        self._disable_proxy(proxy, reason)
                        return {
                            'proxy': f"{proxy.host}:{proxy.port}",
                            'status': 'disabled',
                            'reason': reason,
                            'requests_tested': request_num,
                            'success_count': success_count,
                            'fail_count': fail_count,
                            'elapsed_seconds': time.time() - start_time
                        }

                except Exception as e:
                    fail_count += 1
                    error_msg = str(e)
                    logger.error(f"❌ Request #{request_num} EXCEPTION | Error: {error_msg[:100]} | Proxy: {proxy.host}:{proxy.port}")

                    # Disable proxy on any exception
                    self._disable_proxy(proxy, f"exception_{error_msg[:50]}")
                    return {
                        'proxy': f"{proxy.host}:{proxy.port}",
                        'status': 'disabled',
                        'reason': 'exception',
                        'error': error_msg,
                        'requests_tested': request_num,
                        'success_count': success_count,
                        'fail_count': fail_count,
                        'elapsed_seconds': time.time() - start_time
                    }

                # Wait for the interval
                time.sleep(proxy.interval_ms / 1000.0)

        except KeyboardInterrupt:
            logger.info(f"⏹️  Test interrupted for proxy {proxy.host}:{proxy.port}")
            return {
                'proxy': f"{proxy.host}:{proxy.port}",
                'status': 'interrupted',
                'requests_tested': request_num,
                'success_count': success_count,
                'fail_count': fail_count,
                'elapsed_seconds': time.time() - start_time
            }

    def test_all_proxies(self) -> List[Dict[str, Any]]:
        """Test all enabled proxies in parallel."""
        results = []
        enabled_proxies = [p for p in self.proxies if p.status == "enabled"]

        logger.info(f"Starting parallel rate limit test for {len(enabled_proxies)} enabled proxies")
        logger.info(f"Total proxies: {len(self.proxies)}")

        # Test all proxies in parallel
        with ThreadPoolExecutor(max_workers=len(enabled_proxies)) as executor:
            # Submit all proxy tests
            future_to_proxy = {
                executor.submit(self.test_proxy, proxy): proxy
                for proxy in self.proxies
            }

            # Collect results as they complete
            for future in as_completed(future_to_proxy):
                proxy = future_to_proxy[future]
                try:
                    result = future.result()
                    results.append(result)

                    if result['status'] == 'disabled':
                        logger.warning(f"⚠️  Proxy {proxy.host}:{proxy.port} was disabled after {result['requests_tested']} requests")
                except Exception as e:
                    logger.error(f"Error testing proxy {proxy.host}:{proxy.port}: {e}")
                    results.append({
                        'proxy': f"{proxy.host}:{proxy.port}",
                        'status': 'error',
                        'error': str(e)
                    })

        # Print summary
        logger.info("\n" + "="*50)
        logger.info("RATE LIMIT TEST SUMMARY")
        logger.info("="*50)

        interrupted = sum(1 for r in results if r['status'] == 'interrupted')
        disabled = sum(1 for r in results if r['status'] == 'disabled')
        skipped = sum(1 for r in results if r['status'] == 'skipped')
        errors = sum(1 for r in results if r['status'] == 'error')

        logger.info(f"⏹️  Interrupted proxies: {interrupted}")
        logger.info(f"🔴 Disabled proxies: {disabled}")
        logger.info(f"⏭️  Skipped proxies: {skipped}")
        logger.info(f"❌ Error proxies: {errors}")

        return results


def main():
    """Main entry point."""
    import sys

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"

    tester = RateLimitTester(config_path)
    results = tester.test_all_proxies()

    # Save results to file
    results_file = Path("test_results.json")
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)

    logger.info(f"\nResults saved to {results_file}")


if __name__ == "__main__":
    main()
