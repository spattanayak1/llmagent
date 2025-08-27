import streamlit as st
import os, json, requests, time
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="LLM-Agent (Streamlit)", layout="wide")
st.title("LLM Agent POC — Streamlit (Search + AI Pipe + JS sandbox)")

# --------------------------
# Sidebar / settings
# --------------------------
st.sidebar.header("Settings / Keys")
provider = st.sidebar.selectbox("LLM Provider (client-side ui)", ["OpenAI (server)"], index=0)
openai_api_key = st.sidebar.text_input("OPENAI_API_KEY", value=os.getenv("OPENAI_API_KEY") or "", type="password")
serpapi_key = st.sidebar.text_input("SERPAPI_API_KEY", value=os.getenv("SERPAPI_API_KEY") or "", type="password")
google_api_key = st.sidebar.text_input("GOOGLE_API_KEY", value=os.getenv("GOOGLE_API_KEY") or "", type="password")
google_cx = st.sidebar.text_input("GOOGLE_CX", value=os.getenv("GOOGLE_CX") or "")
aipipe_token = st.sidebar.text_input("AIPIPE_TOKEN (optional)", value=os.getenv("AIPIPE_TOKEN") or "", type="password")
js_sandbox_url = st.sidebar.text_input("JS_SANDBOX_URL (e.g. http://localhost:8081/run_js)", value=os.getenv("JS_SANDBOX_URL") or "http://localhost:8081/run_js")

model = st.sidebar.selectbox("Model", ["gpt-4o-mini", "gpt-4o", "gpt-4.1-nano", "gpt-3.5-turbo-0613"])
max_search_results = st.sidebar.slider("Search results to retrieve", 1, 5, 3)

# session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "running" not in st.session_state:
    st.session_state.running = False

# show conversation
conv_col, input_col = st.columns([4,1])
with conv_col:
    for i, m in enumerate(st.session_state.messages):
        role = m.get("role","assistant")
        if role == "user":
            st.markdown(f"**You:** {m.get('content')}")
        elif role == "assistant":
            st.markdown(f"**Agent:** {m.get('content')}")
        elif role == "tool":
            st.markdown(f"**Tool ({m.get('name')}):** {m.get('content')}", unsafe_allow_html=True)
    st.markdown("---")

# input area
with input_col:
    user_input = st.text_area("User input", height=100, key="ui")
    if st.button("Send"):
        if not user_input.strip():
            st.warning("Please enter something.")
        else:
            st.session_state.messages.append({"role":"user","content": user_input})
            st.session_state.ui = ""  # clear input
            # run agent loop
            st.session_state.running = True

# ---- helper tools ----
def call_openai_chat(messages, model_name, openai_api_key, functions=None):
    """Call OpenAI ChatCompletion with optional function declarations (function-calling)."""
    import openai
    openai.api_key = openai_api_key
    # Build a safe minimal API call
    kwargs = {"model": model_name, "messages": messages}
    if functions:
        kwargs["functions"] = functions
        kwargs["function_call"] = "auto"
    # synchronous for simplicity
    resp = openai.ChatCompletion.create(**kwargs)
    return resp

# function specs for the LLM (OpenAI function-calling style)
LLM_FUNCTIONS = [
    {
        "name": "search",
        "description": "Search the web and return snippet results",
        "parameters": {
            "type":"object",
            "properties": {
                "query":{"type":"string"},
                "k":{"type":"integer"}
            },
            "required":["query"]
        }
    },
    {
        "name": "aipipe",
        "description": "Call AI Pipe proxy with a prompt",
        "parameters": {
            "type":"object",
            "properties": {
                "prompt":{"type":"string"}
            },
            "required":["prompt"]
        }
    },
    {
        "name": "run_js",
        "description": "Execute JS code in a sandbox and return result",
        "parameters": {
            "type":"object",
            "properties": {
                "code":{"type":"string"}
            },
            "required":["code"]
        }
    }
]

def search_tool(query, k=3):
    """Use SerpApi or Google CSE to return top snippet text."""
    if serpapi_key:
        try:
            r = requests.get("https://serpapi.com/search.json", params={"q": query, "api_key": serpapi_key, "num": k})
            j = r.json()
            snippets = []
            for rlt in j.get("organic_results", [])[:k]:
                title = rlt.get("title")
                snippet = rlt.get("snippet") or rlt.get("snippet_text") or ""
                link = rlt.get("link")
                snippets.append(f"- {title}\n{snippet}\n{link}")
            return "\n\n".join(snippets) or json.dumps(j)[:1500]
        except Exception as e:
            return f"SerpApi error: {e}"
    elif google_api_key and google_cx:
        try:
            url = "https://www.googleapis.com/customsearch/v1"
            r = requests.get(url, params={"q": query, "key": google_api_key, "cx": google_cx, "num": k})
            j = r.json()
            snippets = []
            for item in j.get("items", [])[:k]:
                snippets.append(f"- {item.get('title')}\n{item.get('snippet')}\n{item.get('link')}")
            return "\n\n".join(snippets) or json.dumps(j)[:1500]
        except Exception as e:
            return f"Google CSE error: {e}"
    else:
        return "No search provider configured. Set SERPAPI_KEY or GOOGLE_API_KEY + GOOGLE_CX."

def aipipe_tool(prompt_text):
    """Call AI Pipe proxy if token provided. Returns text or error string."""
    if not aipipe_token:
        return "AIPipe token not configured. Set AIPIPE_TOKEN in sidebar/env."
    try:
        # Example: use the aipipe openrouter proxy endpoint for chat completions
        url = "https://aipipe.org/openrouter/v1/chat/completions"
        headers = {"Authorization": f"Bearer {aipipe_token}", "Content-Type":"application/json"}
        body = {"model": model, "messages": [{"role":"user","content": prompt_text}], "max_tokens": 600}
        r = requests.post(url, headers=headers, json=body, timeout=20)
        j = r.json()
        # best-effort extract text
        if "choices" in j and len(j["choices"])>0:
            msg = j["choices"][0].get("message", {}).get("content") or j["choices"][0].get("text") or str(j["choices"][0])
            return msg
        return json.dumps(j)[:1500]
    except Exception as e:
        return f"AIPipe error: {e}"

def run_js_tool(code):
    """Call local JS sandbox (server.js) if available."""
    try:
        r = requests.post(js_sandbox_url, json={"code": code}, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": f"JS sandbox unreachable ({js_sandbox_url}): {e}"}

# ---- agent loop ----
def agent_loop_once():
    """
    Send conversation to LLM; if it requests a function (tool), call the tool and append tool result,
    repeat until LLM stops calling functions.
    """
    # prepare messages for LLM (OpenAI format)
    messages = st.session_state.messages.copy()
    # ensure system prompt exists
    if not any(m.get("role") == "system" for m in messages):
        messages.insert(0, {"role":"system","content":"You are an assistant that may call tools: search, aipipe, run_js. When calling a tool use OpenAI-style function calling. Keep answers concise."})

    # call LLM
    try:
        resp = call_openai_chat(messages=messages, model_name=model, openai_api_key=openai_api_key, functions=LLM_FUNCTIONS)
    except Exception as e:
        st.error(f"LLM call failed: {e}")
        st.session_state.running = False
        return

    choice = resp["choices"][0]["message"]
    # if function call
    if choice.get("function_call"):
        fname = choice["function_call"]["name"]
        raw_args = choice["function_call"].get("arguments") or "{}"
        try:
            args = json.loads(raw_args)
        except:
            args = {}
        # run appropriate tool
        if fname == "search":
            q = args.get("query") or args.get("q") or ""
            k = int(args.get("k", max_search_results))
            tool_out = search_tool(q, k=k)
            # append tool result as a tool message to conversation
            st.session_state.messages.append({"role":"tool","name":"search","content":tool_out})
            # then call LLM again with tool output appended
            return True
        elif fname == "aipipe":
            prompt_text = args.get("prompt") or ""
            out = aipipe_tool(prompt_text)
            st.session_state.messages.append({"role":"tool","name":"aipipe","content": out})
            return True
        elif fname == "run_js":
            code = args.get("code") or ""
            res = run_js_tool(code)
            st.session_state.messages.append({"role":"tool","name":"run_js","content": json.dumps(res, indent=2)[:4000]})
            return True
        else:
            st.session_state.messages.append({"role":"assistant","content": f"(requested unknown tool {fname})"})
            return False
    else:
        # normal assistant response
        content = choice.get("content") or ""
        st.session_state.messages.append({"role":"assistant","content": content})
        return False

# If we just sent a new user message, run the loop until no more function calls (best-effort)
if st.session_state.running:
    # loop with safe max iterations
    for _ in range(6):
        cont = agent_loop_once()
        # refresh display after each step
        st.experimental_rerun()
        if not cont:
            break
    st.session_state.running = False
