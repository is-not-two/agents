"""Submit sourced editorial drafts through normal member API, never self-publish."""

import argparse
import hashlib
import json
import secrets
import ssl
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlparse

from community_native_burst_probe import remote, sql

ORIGIN = "https://8.156.81.128:8771"
SUBJECT = "system:community-curation"
MEMBER = str(uuid.uuid5(uuid.NAMESPACE_URL, ORIGIN + "/community/editorial"))


def quote(value):
    return "'" + value.replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Submit real pending drafts; no publishing"
    )
    args = parser.parse_args()
    items = json.loads(Path("data/community/curated_notes.json").read_text(encoding="utf-8"))
    assert len(items) == 3 and len({item["slug"] for item in items}) == 3
    allowed = {"www.feishu.cn", "support.microsoft.com"}
    for item in items:
        assert 1 <= len(item["title"]) <= 120 and 1 <= len(item["body"]) < 19000
        assert item["sources"] and all(
            urlparse(url).scheme == "https" and urlparse(url).hostname in allowed
            for url in item["sources"]
        )
        assert "未" in item["body"] and "复核和评分" in item["body"]
    if not args.apply:
        print(
            json.dumps(
                {
                    "validated_drafts": len(items),
                    "action": "none; use --apply to submit pending only",
                }
            )
        )
        return
    certificate = remote("cat /var/lib/shilie-preview/app/credentials/server.crt")
    context = ssl.create_default_context(cadata=certificate)
    jar = CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), urllib.request.HTTPSHandler(context=context)
    )

    def call(path, data=None, method=None):
        request = urllib.request.Request(
            ORIGIN + "/api/community/" + path,
            data=json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None,
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
            method=method,
        )
        with opener.open(request, timeout=10) as response:
            return response.status, json.load(response) if response.status != 204 else {}

    invitation = secrets.token_urlsafe(32)
    invite_digest = hashlib.sha256(invitation.encode()).hexdigest()
    records = []
    try:
        sql(
            f"INSERT INTO community.members(id,subject,display_name,role) VALUES('{MEMBER}','{SUBJECT}','资料整理助手（未实测）','member') ON CONFLICT(subject) DO NOTHING"
        )
        actual = sql(f"SELECT id||'|'||role FROM community.members WHERE subject='{SUBJECT}'")
        assert actual == MEMBER + "|member", "editorial identity differs; inspect, do not overwrite"
        sql(
            f"INSERT INTO community.invitations(digest,member_id,expires_at) VALUES(decode('{invite_digest}','hex'),'{MEMBER}',now()+interval '5 minutes')"
        )
        assert call("session", {"token": invitation})[0] == 201
        for item in items:
            request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, ORIGIN + "/curated/" + item["slug"]))
            existing = sql(
                f"SELECT id FROM community.posts WHERE author_id='{MEMBER}' AND request_id='{request_id}'"
            )
            if existing:
                records.append(
                    {"slug": item["slug"], "id": existing, "action": "existing_not_modified"}
                )
                continue
            body = item["body"] + "\n\n官方来源\n" + "\n".join(item["sources"])
            status, result = call(
                "posts", {"request_id": request_id, "title": item["title"], "body": body}
            )
            assert status == 201
            identifier = str(uuid.UUID(result["id"]))
            stored = sql(
                f"SELECT state||'|'||score::text FROM community.posts WHERE id='{identifier}' AND author_id='{MEMBER}'"
            )
            assert stored == "pending|0"
            assert (
                sql(f"SELECT count(*) FROM community.public_topics WHERE id='{identifier}'") == "0"
            )
            records.append(
                {"slug": item["slug"], "id": identifier, "action": "submitted_pending", "score": 0}
            )
        destination = Path("output/community-vue/curated-drafts-receipt.json")
        destination.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "drafts": records,
                    "published_by_this_script": 0,
                    "review_url": ORIGIN + "/static/vue/community.html#/review",
                }
            ),
            flush=True,
        )
    finally:
        session = next(
            (cookie.value for cookie in jar if cookie.name == "__Secure-community_session"), None
        )
        try:
            if session:
                assert call("session", method="DELETE")[0] == 204
        finally:
            sql(
                f"DELETE FROM community.invitations WHERE digest=decode('{invite_digest}','hex') AND member_id='{MEMBER}'"
            )
            if session:
                digest = hashlib.sha256(session.encode()).hexdigest()
                sql(
                    f"DELETE FROM community.sessions WHERE token_digest=decode('{digest}','hex') AND member_id='{MEMBER}'"
                )
            print("temporary_editorial_credentials_removed", flush=True)


if __name__ == "__main__":
    main()
