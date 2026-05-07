import type { Plugin } from "@opencode-ai/plugin"

const TARGET_DIR = "knowledge/articles/"
const TARGET_EXT = ".json"
const TOOLS_TO_WATCH = new Set(["write", "edit"])
const SCRIPT = "hooks/validate_json.py"

function getFilePath(args: any): string | undefined {
  return args?.file_path ?? args?.filePath
}

async function detectPython($: any): Promise<string> {
  const isWin = process.platform === "win32"
  if (isWin) {
    const probe = await $`where python`.nothrow()
    return probe.exitCode === 0 ? "python" : "python3"
  }
  const probe = await $`which python3`.nothrow()
  return probe.exitCode === 0 ? "python3" : "python"
}

export const ValidatePlugin: Plugin = async (ctx) => {
  const { client, $: shell } = ctx
  let pythonCmd = ""

  return {
    "tool.execute.after": async (input, output) => {
      if (!TOOLS_TO_WATCH.has(input.tool)) return

      const filePath = getFilePath(input.args)
      if (
        !filePath ||
        !filePath.includes(TARGET_DIR) ||
        !filePath.endsWith(TARGET_EXT)
      ) {
        return
      }

      if (!pythonCmd) {
        pythonCmd = await detectPython(shell)
      }

      try {
        const result =
          await shell`${pythonCmd} ${SCRIPT} ${filePath}`.nothrow()

        const errText = result.stderr?.text?.() ?? ""
        const outText = result.stdout?.text?.() ?? ""

        if (result.exitCode !== 0) {
          const detail = errText || outText
          await client.app.log({
            body: {
              service: "validate-hook",
              level: "error",
              message: `Validation FAILED: ${filePath}`,
              extra: { detail },
            },
          })
          output.output += `\n\n[validate] FAILED ${filePath}:\n${detail}`
        } else {
          await client.app.log({
            body: {
              service: "validate-hook",
              level: "debug",
              message: `Validation PASSED: ${filePath}`,
            },
          })
        }
      } catch (err: any) {
        await client.app.log({
          body: {
            service: "validate-hook",
            level: "error",
            message: `Hook error for ${filePath}`,
            extra: { error: String(err?.message ?? err) },
          },
        })
      }
    },
  }
}
