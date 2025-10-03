# Rate Limit Tester

Universal tool for testing API rate limits across multiple proxies. Automatically disables proxies that encounter errors (Cloudflare blocks, rate limits, or validation failures).

## Features

- 🔄 Test multiple proxies with different rate limit intervals
- 🚫 Automatically disable proxies on errors (Cloudflare, rate limits, API failures)
- 🔧 Universal configuration - works with any API
- 📊 Detailed test results and statistics
- 💾 Auto-save config with disabled proxies

## Configuration

Copy `config.example.json` to `config.json` and edit it:

```json
{
  "api": {
    "url": "https://api.example.com/endpoint",
    "method": "GET",
    "params": {
      "key": "value"
    },
    "headers": {
      "User-Agent": "Mozilla/5.0...",
      "Accept": "application/json"
    },
    "timeout_ms": 10000,
    "validation": {
      "success_field": "success",
      "success_value": true,
      "cloudflare_indicators": ["cf-ray", "cloudflare"],
      "ratelimit_indicators": ["rate limit", "429"]
    }
  },
  "disable_policy": {
    "consecutive_threshold": 3,
    "percentage_threshold": 5
  },
  "proxies": [
    "http:host:port:user:pass:enabled:interval_ms"
  ],
  "lifetimes": {
    "host:port": {
      "ip": "host:port",
      "interval": 6000,
      "lifetime": 355,
      "errors": 100,
      "errors_percents": 5.0
    }
  }
}
```

### Proxy Format

`protocol:host:port:username:password:status:interval_ms`

- **protocol**: `http` or `socks5`
- **host**: Proxy hostname/IP
- **port**: Proxy port
- **username**: Auth username
- **password**: Auth password
- **status**: `enabled` or `disabled`
- **interval_ms**: Request interval in milliseconds (e.g., 500 = 2 req/sec)

### Disable Policy

Controls when to automatically disable a proxy:

- **consecutive_threshold**: Disable after N consecutive failures (default: 3)
- **percentage_threshold**: Disable if error rate exceeds N% (default: 5)

### Lifetimes

Automatically populated when proxies are disabled. Contains detailed statistics:

- **ip**: Proxy address (host:port)
- **interval**: Request interval in milliseconds
- **lifetime**: How long the proxy worked before being disabled (ms)
- **errors**: Total number of errors
- **errors_percents**: Error rate percentage

### Validation Rules

The tool checks responses for:

1. **HTTP Status**: Must be 200 (429 = rate limit)
2. **Cloudflare**: Searches for indicators in response text
3. **Rate Limit**: Searches for rate limit messages
4. **Success Field**: Checks JSON field (e.g., `{"success": true}`)

## Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Copy example config
cp config.example.json config.json

# Edit config.json with your API and proxies
# Then run tests
python ratelimit_tester.py

# Or with custom config
python ratelimit_tester.py path/to/config.json
```

## Output

- **Console**: Live test progress with emoji indicators
- **test_results.json**: Detailed results for each proxy
- **config.json**: Auto-updated with disabled proxies
- **config.json.backup**: Backup before changes

## Example Output

```
Testing proxy proxy1.example.com:8080 with interval 4500ms
✅ Request 1/10: OK
✅ Request 2/10: OK
❌ Request 3/10: FAILED - ratelimit_error
🔴 DISABLED proxy proxy1.example.com:8080 - Reason: ratelimit_error

==================================================
RATE LIMIT TEST SUMMARY
==================================================
✅ Enabled proxies: 7
🔴 Disabled proxies: 3
⏭️  Skipped proxies: 0
```

## Use Cases

- Finding optimal rate limits for proxies
- Testing API proxy compatibility
- Detecting blocked/rate-limited proxies
- Validating proxy pool health

## License

MIT
