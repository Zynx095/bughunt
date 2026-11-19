"""Deterministic threat and prompt-injection detectors.

These are transparent pattern heuristics: every finding names the rule that
fired so an analyst can audit it. They reduce risk; they do not guarantee
detection of novel or obfuscated attacks.
"""
from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

SEVERITY_WEIGHT = {"critical": 0.6, "high": 0.4, "medium": 0.2, "low": 0.08}


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    severity: str
    pattern: re.Pattern[str]
    description: str


def _r(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


THREAT_RULES: list[Rule] = [
    # Injection
    Rule("sqli.union", "sql_injection", "high", _r(r"\bunion\b\s+(all\s+)?select\b"), "UNION-based SQL injection"),
    Rule("sqli.tautology", "sql_injection", "high", _r(r"['\"]\s*(or|and)\s+['\"]?\w+['\"]?\s*=\s*['\"]?\w+"), "Boolean tautology (e.g. ' OR '1'='1)"),
    Rule("sqli.stacked", "sql_injection", "critical", _r(r";\s*(drop|truncate|alter|delete\s+from)\s+\w+"), "Stacked destructive SQL statement"),
    Rule("sqli.timing", "sql_injection", "high", _r(r"\b(sleep|pg_sleep|benchmark|waitfor\s+delay)\s*\("), "Time-based SQL injection"),
    Rule("xss.script", "xss", "high", _r(r"<\s*script\b"), "Inline <script> tag"),
    Rule("xss.handler", "xss", "medium", _r(r"<[^>]+\bon(error|load|click|mouseover|focus)\s*="), "HTML event-handler injection"),
    Rule("xss.jsurl", "xss", "medium", _r(r"javascript\s*:"), "javascript: URL"),
    Rule("traversal.dots", "path_traversal", "high", _r(r"(\.\.[/\\]){2,}|%2e%2e(%2f|%5c)"), "Directory traversal sequence"),
    Rule("traversal.sensitive", "path_traversal", "high", _r(r"/etc/(passwd|shadow)|\\windows\\system32"), "Sensitive system path"),
    Rule("cmd.chain", "command_injection", "high", _r(r"[;&|]\s*(rm\s+-|wget\s|curl\s|nc\s|bash\b|sh\s+-c|powershell\b|cmd(\.exe)?\s*/c)"), "Shell command chaining"),
    Rule("cmd.subst", "command_injection", "medium", _r(r"\$\([^)]{1,200}\)|`[^`\n]{1,200}`"), "Shell command substitution"),
    # Secrets exposure
    Rule("secret.aws", "secret_exposure", "critical", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key ID"),
    Rule("secret.google", "secret_exposure", "critical", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "Google API key"),
    Rule("secret.github", "secret_exposure", "critical", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "GitHub token"),
    Rule("secret.privkey", "secret_exposure", "critical", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "Private key material"),
    Rule("secret.assign", "secret_exposure", "medium", _r(r"\b(api[_-]?key|secret|passwd|password|token)\s*[:=]\s*['\"]?[^\s'\"]{8,}"), "Credential assignment"),
    # Social engineering / phishing language
    Rule("phish.urgency", "social_engineering", "medium", _r(r"\b(urgent|immediately|within 24 hours|final notice|act now|last warning)\b"), "Urgency pressure"),
    Rule("phish.account", "social_engineering", "medium", _r(r"\b(verify|confirm|update|validate)\s+(your\s+)?(account|password|identity|login|payment|details)\b"), "Credential/account verification request"),
    Rule("phish.suspend", "social_engineering", "medium", _r(r"\b(account|access)\s+(will be|has been)\s+(suspended|locked|closed|terminated|disabled)\b"), "Account suspension threat"),
    Rule("phish.payment", "social_engineering", "high", _r(r"\b(gift\s*cards?|wire\s+transfer|bitcoin|crypto\s*wallet|western union)\b"), "Unusual payment request"),
    Rule("phish.cta", "social_engineering", "low", _r(r"\b(click (here|the link|below)|log ?in (here|now))\b"), "Generic call-to-action link"),
]

SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly", "shorturl.at"}
RISKY_TLDS = {"zip", "mov", "xyz", "top", "click", "country", "gq", "tk", "ml", "cf", "work", "rest", "cam"}
BRANDS = {"paypal", "microsoft", "office365", "apple", "amazon", "google", "netflix", "facebook", "instagram",
          "whatsapp", "dhl", "fedex", "chase", "wellsfargo", "hsbc", "barclays", "linkedin", "outlook"}
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0).rstrip(".,;:!?") for m in URL_RE.finditer(text)))


def _registered_domain(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def analyse_url(url: str) -> list[dict]:
    findings: list[dict] = []
    raw = url if "://" in url else f"http://{url}"
    try:
        parts = urlsplit(raw)
    except ValueError:
        return [{"rule": "url.malformed", "category": "suspicious_url", "severity": "medium", "description": "Malformed URL", "evidence": url}]
    host = (parts.hostname or "").lower()

    def add(rule: str, sev: str, desc: str) -> None:
        findings.append({"rule": rule, "category": "suspicious_url", "severity": sev, "description": desc, "evidence": url})

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            add("url.internal_ip", "high", "URL targets an internal/link-local address (SSRF risk)")
        else:
            add("url.ip_host", "medium", "URL uses a raw IP address instead of a domain")
    except ValueError:
        pass
    if "@" in (parts.netloc or ""):
        add("url.userinfo", "high", "'@' in URL authority can disguise the real destination")
    if "xn--" in host:
        add("url.punycode", "medium", "Punycode (possible homograph) domain")
    if host in SHORTENERS:
        add("url.shortener", "low", "URL shortener hides the destination")
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    if tld in RISKY_TLDS:
        add("url.risky_tld", "medium", f"Top-level domain '.{tld}' is frequently abused")
    if host.count(".") >= 4:
        add("url.deep_subdomain", "low", "Unusually deep subdomain nesting")
    registered = _registered_domain(host)
    for brand in BRANDS:
        if brand in host and not registered.startswith(brand + "."):
            add("url.brand_lookalike", "high", f"Brand name '{brand}' used outside the brand's own domain")
            break
    if parts.scheme == "http" and host:
        add("url.no_tls", "low", "Unencrypted http:// link")
    if len(url) > 150:
        add("url.long", "low", "Very long URL")
    return findings


def noisy_or(findings: list[dict]) -> float:
    """Combine independent finding weights: 1 - prod(1 - w). Bounded in [0, 100]."""
    p = 1.0
    for f in findings:
        p *= 1 - SEVERITY_WEIGHT.get(f["severity"], 0.05)
    return round((1 - p) * 100, 1)


def band(score: float) -> str:
    return "critical" if score >= 80 else "high" if score >= 55 else "medium" if score >= 25 else "low"


def threat_scan(text: str) -> dict:
    findings: list[dict] = []
    for rule in THREAT_RULES:
        m = rule.pattern.search(text)
        if m:
            findings.append({"rule": rule.id, "category": rule.category, "severity": rule.severity,
                             "description": rule.description, "evidence": m.group(0)[:120]})
    urls = extract_urls(text)
    for url in urls:
        findings.extend(analyse_url(url))
    score = noisy_or(findings)
    categories = sorted({f["category"] for f in findings})
    return {"risk_score": score, "risk_band": band(score), "findings": findings, "categories": categories, "urls": urls}


# ---------------------------------------------------------------- prompt injection
INJECTION_RULES: list[Rule] = [
    Rule("pi.ignore", "instruction_override", "high", _r(r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|system|all)\b[^.\n]{0,20}\b(instructions?|prompts?|rules|directions)\b"), "Attempts to override prior instructions"),
    Rule("pi.reveal", "prompt_exfiltration", "high", _r(r"\b(reveal|print|show|repeat|output|leak)\b[^.\n]{0,30}\b(system prompt|hidden (instructions|prompt)|your instructions|initial prompt)\b"), "Attempts to extract the system prompt"),
    Rule("pi.persona", "role_hijack", "medium", _r(r"\b(you are now|from now on you are|pretend (to be|you are)|act as)\b[^.\n]{0,60}\b(unrestricted|unfiltered|jailbroken|dan|without (any )?(rules|restrictions|limits))\b"), "Persona hijack toward an unrestricted mode"),
    Rule("pi.jailbreak", "role_hijack", "medium", _r(r"\b(developer mode|jailbreak|dan mode|do anything now)\b"), "Known jailbreak phrasing"),
    Rule("pi.roletag", "delimiter_injection", "medium", _r(r"<\|im_start\|>|<\|system\|>|^\s*#{2,3}\s*system\b|^\s*\[system\]|^\s*system\s*:"), "Fake role/system delimiter"),
    Rule("pi.secrecy", "deception", "medium", _r(r"\b(do not|don't|never)\s+(tell|inform|mention|reveal)\b[^.\n]{0,20}\b(the )?(user|human|operator)\b"), "Instructs the model to hide actions from the user"),
    Rule("pi.exfil_md", "data_exfiltration", "high", _r(r"!\[[^\]]*\]\(\s*https?://[^)\s]*\?[^)\s]*=[^)]*\)"), "Markdown image with query string (exfiltration channel)"),
    Rule("pi.exfil_send", "data_exfiltration", "high", _r(r"\b(send|post|upload|forward|email)\b[^.\n]{0,40}\b(conversation|chat history|credentials|api keys?|secrets?|all (the )?data)\b[^.\n]{0,20}\b(to|at)\b"), "Instructs sending sensitive data elsewhere"),
    Rule("pi.tool_abuse", "tool_abuse", "high", _r(r"\b(approve|authori[sz]e|sign|transfer|delete|execute)\b[^.\n]{0,40}\b(without|bypass(ing)?|skip(ping)?)\b[^.\n]{0,20}\b(approval|review|verification|checks?|confirmation)\b"), "Requests a sensitive action that bypasses controls"),
]
INVISIBLE_RE = re.compile("[​-‏⁠-⁤﻿\U000e0000-\U000e007f]")
BASE64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


def prompt_injection_scan(text: str) -> dict:
    normalised = unicodedata.normalize("NFKC", text)
    signals: list[dict] = []
    for rule in INJECTION_RULES:
        m = rule.pattern.search(normalised)
        if m:
            signals.append({"rule": rule.id, "category": rule.category, "severity": rule.severity,
                            "description": rule.description, "evidence": m.group(0)[:120]})
    hidden = INVISIBLE_RE.findall(text)
    if hidden:
        signals.append({"rule": "pi.invisible_unicode", "category": "hidden_content", "severity": "high",
                        "description": f"{len(hidden)} invisible/tag Unicode characters (possible hidden instructions)",
                        "evidence": " ".join(f"U+{ord(c):04X}" for c in hidden[:8])})
    if BASE64_BLOB_RE.search(text):
        signals.append({"rule": "pi.encoded_blob", "category": "obfuscation", "severity": "low",
                        "description": "Long base64-like blob (possible encoded payload)", "evidence": "[base64 blob]"})
    score = noisy_or(signals)
    verdict = "block" if score >= 55 else "review" if score >= 20 else "allow"
    return {"injection_score": score, "verdict": verdict, "signals": signals}
