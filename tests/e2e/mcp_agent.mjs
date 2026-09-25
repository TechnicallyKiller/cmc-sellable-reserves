// Independent test of the Sellable Reserves MCP server:
// 1) the official MCP TypeScript SDK client, both protocol eras (legacy initialize, and 2026-07-28);
// 2) a real LLM agent that decides which tools to call. Any OpenAI-compatible chat endpoint works:
//    LLM_BASE_URL (default Groq), LLM_MODEL (default openai/gpt-oss-120b), LLM_API_KEY.
//
//   cd tests/e2e && npm install
//   MCP_URL=http://localhost:8000/mcp LLM_API_KEY=... node mcp_agent.mjs ["your question"]
import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client';

const URL_ = process.env.MCP_URL || 'http://localhost:8000/mcp';

async function connect(label, versionNegotiation) {
  const client = new Client({ name: 'sr-agent-test', version: '1.0.0' }, versionNegotiation ? { versionNegotiation } : {});
  await client.connect(new StreamableHTTPClientTransport(new URL(URL_)));
  const tools = (await client.listTools()).tools;
  console.log(`[${label}] connected, tools: ${tools.map(t => t.name).join(', ')}`);
  return { client, tools };
}

// --- 1. protocol, both eras ---
const legacy = await connect('legacy (SDK default)');
const r1 = await legacy.client.callTool({ name: 'get_exchange_reserves', arguments: { exchange: 'Blockfinex' } });
console.log(`[legacy] get_exchange_reserves -> isError=${r1.isError}, 50% in: ${JSON.stringify(r1.structuredContent?.days_until_sellable)}`);
await legacy.client.close();

const modern = await connect('modern (pinned 2026-07-28)', { mode: { pin: '2026-07-28' } });
const r2 = await modern.client.callTool({ name: 'list_exchanges', arguments: { filter: 'notice' } });
console.log(`[modern] list_exchanges(notice) -> ${r2.structuredContent?.exchanges?.map(e => e.exchange).join(', ')}`);
const bad = await modern.client.callTool({ name: 'token_exposure', arguments: { symbol: 'NOTATOKEN' } });
console.log(`[modern] token_exposure(NOTATOKEN) -> isError=${bad.isError}: ${bad.content[0].text}`);

// --- 2. a real agent decides which tools to call ---
const question = process.argv[2] || "I keep funds on LBank and Bitget. Before I move money, compare how much of each one's reserves could actually be sold within a week, and tell me what the biggest illiquid holding is on each.";
const tools = modern.tools.map(t => ({ type: 'function', function: { name: t.name, description: t.description, parameters: t.inputSchema } }));
const messages = [
  { role: 'system', content: 'You are an assistant that helps a user who keeps crypto on exchanges. Use the provided tools for any numbers; never invent figures. Do not give buy/sell/withdraw advice; describe what the data shows and its limits.' },
  { role: 'user', content: question },
];
console.log(`\nAGENT QUESTION: ${question}\n`);
for (let turn = 0; turn < 6; turn++) {
  const ask = choice => fetch(`${process.env.LLM_BASE_URL || 'https://api.groq.com/openai/v1'}/chat/completions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${process.env.LLM_API_KEY}`, 'Content-Type': 'application/json', 'User-Agent': 'sr-agent-test/1.0' },
    body: JSON.stringify({ model: process.env.LLM_MODEL || 'openai/gpt-oss-120b', temperature: 0.2, messages, tools, tool_choice: choice }),
  });
  let resp = await ask('auto');
  // Some models (seen with gpt-oss) call a tool that doesn't exist; the endpoint rejects it with 400. Retry without tools.
  if (resp.status === 400) { console.log('  (model tried a non-existent tool; retrying with tool_choice=none)'); resp = await ask('none'); }
  if (!resp.ok) { console.log('LLM error', resp.status, (await resp.text()).slice(0, 200)); break; }
  const msg = (await resp.json()).choices[0].message;
  messages.push(msg);
  if (!msg.tool_calls?.length) { console.log('AGENT ANSWER:\n' + msg.content); break; }
  for (const tc of msg.tool_calls) {
    const args = JSON.parse(tc.function.arguments || '{}');
    const out = await modern.client.callTool({ name: tc.function.name, arguments: args });
    console.log(`  -> agent called ${tc.function.name}(${JSON.stringify(args)})  isError=${out.isError}`);
    messages.push({ role: 'tool', tool_call_id: tc.id, content: out.content.map(c => c.text).join('\n') });
  }
}
await modern.client.close();
