# UI / Chat Engine — discussion summary

## What we were deciding

We were trying to understand whether the current chat UI should stay, and how Claude/Codex could be used without letting them bypass the harness.

## Main conclusion

The safe design is:

- keep the UI if you want a controlled front door
- move execution authority into a local MCP server
- make `run_tool` the only execution entrypoint
- enforce `onboard → judge → run/refuse → evaluate/diagnose` on the server

## Important nuance

MCP does **not** magically remove a client’s native powers.

So:

- if a client already has shell/exec access, MCP does not cancel that
- the server only controls what happens through its own tool surface
- safety comes from **not exposing raw execution anywhere**

## Why the UI still matters

The UI helps if it is the only client the user uses, because it can avoid exposing a shell/exec path at all.

That makes the UI a containment layer:

- user chats in the UI
- the UI calls only MCP tools
- the server decides whether to run anything

## Deployment patterns we compared

1. **Custom UI only + local MCP server**
   - strongest control
   - best fit if the harness is the product

2. **Claude Desktop / Codex only + local MCP server**
   - easiest to prototype
   - weaker containment because the client may already have local powers

3. **Hybrid: custom UI + Claude/Codex clients**
   - best migration path
   - lets you compare the new MCP flow against the current UI

## What we decided to do first

If you want the clearest control boundary, keep the current UI and make it a thin client over a local MCP server.

If you want to experiment faster, you can also connect Claude Desktop/Codex to the same server later.

## Practical enforcement checklist

- do not expose raw shell/exec tools
- make `run_tool` self-guarding
- keep all contract checks server-side
- use a server-issued run id or state machine
- reject requests that try to skip stages

## Bottom line

The server must be the policy boundary.

The UI can help keep the client surface narrow, but the actual protection comes from the MCP tool design and from never giving the model a separate execution path.

