const express = require("express");
const bodyParser = require("body-parser");
const cors = require("cors");
const { VM } = require("vm2");

const app = express();
app.use(cors());
app.use(bodyParser.json({limit: "1mb"}));

app.post("/run_js", async (req, res) => {
  const { code } = req.body || {};
  if (typeof code !== "string") {
    return res.status(400).json({ error: "code (string) required" });
  }

  // capture console messages
  const logs = [];
  const sandboxConsole = {
    log: (...args) => logs.push(args.map(a => {
      try { return JSON.stringify(a); } catch(e){ return String(a); }
    }).join(" ")),
    error: (...args) => logs.push("[ERROR] " + args.join(" "))
  };

  const vm = new VM({
    timeout: 1200, // 1.2s
    sandbox: { console: sandboxConsole },
    eval: false,
    wasm: false
  });

  try {
    // Wrap in an IIFE so `return` can be used in code
    const wrapped = `(function(){ ${code} })()`;
    const result = vm.run(wrapped);
    // convert result to string safely
    let out;
    try { out = typeof result === "string" ? result : JSON.stringify(result); }
    catch(e){ out = String(result); }
    res.json({ result: out, logs });
  } catch (err) {
    res.json({ error: String(err), logs });
  }
});

const port = process.env.JS_SANDBOX_PORT || 8081;
app.listen(port, () => console.log(`JS sandbox listening on ${port}`));
