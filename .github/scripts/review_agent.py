import json, os, subprocess, urllib.request, urllib.error

MODEL = "openai/gpt-4o"
MAX_CHARS = 60000
INSTRUCTIONS_PATH = ".github/review-instructions.md"


def changed_files(base_ref):
    out = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [f for f in out.splitlines() if f.strip()]


def notebook_code(path):
    with open(path) as f:
        nb = json.load(f)
    cells = [
        "".join(c["source"])
        for c in nb.get("cells", [])
        if c.get("cell_type") == "code"
    ]
    return "\n\n# ---- cell ----\n\n".join(cells)


def get_review_payload(base_ref):
    parts = []
    for path in changed_files(base_ref):
        if not os.path.exists(path) or path.startswith(".github/"):
            continue
        if path.endswith(".ipynb"):
            parts.append(
                f"### Notebook: {path} (code cells only)\n\n"
                f"```python\n{notebook_code(path)}\n```"
            )
        elif path.endswith(".py"):
            d = subprocess.run(
                ["git", "diff", f"origin/{base_ref}...HEAD", "--", path],
                capture_output=True, text=True, check=True,
            ).stdout
            parts.append(f"### Diff: {path}\n\n```diff\n{d}\n```")
    return "\n\n".join(parts)


def build_prompt(instructions, code):
    return f"""You are reviewing a pull request. Follow the review instructions below exactly — they define what this repository cares about. Do not comment on things the instructions do not ask about.

<review_instructions>
{instructions}
</review_instructions>

<changed_code>
{code}
</changed_code>

Write the review as GitHub-flavoured markdown. Quote the exact line you are commenting on. If nothing in the instructions applies, say so in one sentence rather than inventing findings."""

def call_model(prompt):
    req = urllib.request.Request(
        os.environ["FOUNDRY_ENDPOINT"],
        data=json.dumps({
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1500,
        }).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['FOUNDRY_KEY']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return f"Inference failed: HTTP {e.code}\n\n```\n{e.read().decode()[:800]}\n```"

payload = get_review_payload(os.environ["BASE_REF"])

if not payload.strip():
    body = "No reviewable code changes in this pull request."
else:
    instructions = open(INSTRUCTIONS_PATH).read()
    body = call_model(build_prompt(instructions, payload[:MAX_CHARS]))

with open("review.md", "w") as f:
    f.write("## Automated review\n\n" + body)