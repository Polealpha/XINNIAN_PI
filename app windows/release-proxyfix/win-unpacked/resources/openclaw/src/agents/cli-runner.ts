import type { ImageContent } from "@mariozechner/pi-ai";
import type { ThinkLevel } from "../auto-reply/thinking.js";
import type { OpenClawConfig } from "../config/config.js";
import type { EmbeddedPiRunResult } from "./pi-embedded-runner.js";
import { resolveHeartbeatPrompt } from "../auto-reply/heartbeat.js";
import { shouldLogVerbose } from "../globals.js";
import { isTruthyEnvValue } from "../infra/env.js";
import { createSubsystemLogger } from "../logging/subsystem.js";
import { runCommandWithTimeout } from "../process/exec.js";
import { resolveSessionAgentIds } from "./agent-scope.js";
import { makeBootstrapWarn, resolveBootstrapContextForRun } from "./bootstrap-files.js";
import { resolveCliBackendConfig } from "./cli-backends.js";
import {
  appendImagePathsToPrompt,
  buildCliArgs,
  buildSystemPrompt,
  cleanupResumeProcesses,
  cleanupSuspendedCliProcesses,
  enqueueCliRun,
  normalizeCliModel,
  parseCliJson,
  parseCliJsonl,
  resolvePromptInput,
  resolveSessionIdToSend,
  resolveSystemPromptUsage,
  writeCliImages,
} from "./cli-runner/helpers.js";
import { resolveOpenClawDocsPath } from "./docs-path.js";
import { FailoverError, resolveFailoverStatus } from "./failover-error.js";
import { classifyFailoverReason, isFailoverErrorMessage } from "./pi-embedded-helpers.js";
import { redactRunIdentifier, resolveRunWorkspaceDir } from "./workspace-run.js";

const log = createSubsystemLogger("agent/claude-cli");

const CODEX_BENIGN_WARNING_PATTERNS = [
  "warn codex_core::state_db: state db record_discrepancy",
  "warn codex_core::shell_snapshot: failed to create shell snapshot for powershell",
] as const;

function isCodexBenignWarningOnly(stderr: string): boolean {
  const lines = stderr
    .split(/\r?\n/g)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) {
    return false;
  }
  let hasKnownWarning = false;
  for (const line of lines) {
    const lower = line.toLowerCase();
    if (lower.includes("error") || lower.includes("panic") || lower.includes("fatal")) {
      return false;
    }
    if (!lower.includes("warn")) {
      return false;
    }
    const known = CODEX_BENIGN_WARNING_PATTERNS.some((pattern) => lower.includes(pattern));
    if (!known) {
      return false;
    }
    hasKnownWarning = true;
  }
  return hasKnownWarning;
}

export async function runCliAgent(params: {
  sessionId: string;
  sessionKey?: string;
  agentId?: string;
  sessionFile: string;
  workspaceDir: string;
  config?: OpenClawConfig;
  prompt: string;
  provider: string;
  model?: string;
  thinkLevel?: ThinkLevel;
  timeoutMs: number;
  runId: string;
  extraSystemPrompt?: string;
  streamParams?: import("../commands/agent/types.js").AgentStreamParams;
  ownerNumbers?: string[];
  cliSessionId?: string;
  images?: ImageContent[];
  isHeartbeat?: boolean;
}): Promise<EmbeddedPiRunResult> {
  const started = Date.now();
  const workspaceResolution = resolveRunWorkspaceDir({
    workspaceDir: params.workspaceDir,
    sessionKey: params.sessionKey,
    agentId: params.agentId,
    config: params.config,
  });
  const resolvedWorkspace = workspaceResolution.workspaceDir;
  const redactedSessionId = redactRunIdentifier(params.sessionId);
  const redactedSessionKey = redactRunIdentifier(params.sessionKey);
  const redactedWorkspace = redactRunIdentifier(resolvedWorkspace);
  if (workspaceResolution.usedFallback) {
    log.warn(
      `[workspace-fallback] caller=runCliAgent reason=${workspaceResolution.fallbackReason} run=${params.runId} session=${redactedSessionId} sessionKey=${redactedSessionKey} agent=${workspaceResolution.agentId} workspace=${redactedWorkspace}`,
    );
  }
  const workspaceDir = resolvedWorkspace;

  const backendResolved = resolveCliBackendConfig(params.provider, params.config);
  if (!backendResolved) {
    throw new Error(`Unknown CLI backend: ${params.provider}`);
  }
  const backend = backendResolved.config;
  const modelId = (params.model ?? "default").trim() || "default";
  const normalizedModel = normalizeCliModel(modelId, backend);
  const modelDisplay = `${params.provider}/${modelId}`;

  const extraSystemPrompt = [
    params.extraSystemPrompt?.trim(),
    "Tools are disabled in this session. Do not call tools.",
  ]
    .filter(Boolean)
    .join("\n");

  const sessionLabel = params.sessionKey ?? params.sessionId;
  const { contextFiles } = await resolveBootstrapContextForRun({
    workspaceDir,
    config: params.config,
    sessionKey: params.sessionKey,
    sessionId: params.sessionId,
    warn: makeBootstrapWarn({ sessionLabel, warn: (message) => log.warn(message) }),
  });
  const { defaultAgentId, sessionAgentId } = resolveSessionAgentIds({
    sessionKey: params.sessionKey,
    config: params.config,
  });
  const heartbeatPrompt =
    params.isHeartbeat && sessionAgentId === defaultAgentId
      ? resolveHeartbeatPrompt(params.config?.agents?.defaults?.heartbeat?.prompt)
      : undefined;
  const docsPath = await resolveOpenClawDocsPath({
    workspaceDir,
    argv1: process.argv[1],
    cwd: process.cwd(),
    moduleUrl: import.meta.url,
  });
  const systemPrompt = buildSystemPrompt({
    workspaceDir,
    config: params.config,
    defaultThinkLevel: params.thinkLevel,
    extraSystemPrompt,
    ownerNumbers: params.ownerNumbers,
    heartbeatPrompt,
    docsPath: docsPath ?? undefined,
    tools: [],
    contextFiles,
    modelDisplay,
    agentId: sessionAgentId,
  });

  const { sessionId: cliSessionIdToSend, isNew } = resolveSessionIdToSend({
    backend,
    cliSessionId: params.cliSessionId,
  });
  const useResume = Boolean(
    params.cliSessionId &&
    cliSessionIdToSend &&
    backend.resumeArgs &&
    backend.resumeArgs.length > 0,
  );
  const sessionIdSent = cliSessionIdToSend
    ? useResume || Boolean(backend.sessionArg) || Boolean(backend.sessionArgs?.length)
      ? cliSessionIdToSend
      : undefined
    : undefined;
  const systemPromptArg = resolveSystemPromptUsage({
    backend,
    isNewSession: isNew,
    systemPrompt,
  });

  let imagePaths: string[] | undefined;
  let cleanupImages: (() => Promise<void>) | undefined;
  let prompt = params.prompt;
  if (params.images && params.images.length > 0) {
    const imagePayload = await writeCliImages(params.images);
    imagePaths = imagePayload.paths;
    cleanupImages = imagePayload.cleanup;
    if (!backend.imageArg) {
      prompt = appendImagePathsToPrompt(prompt, imagePaths);
    }
  }

  const { argsPrompt, stdin } = resolvePromptInput({
    backend,
    prompt,
  });
  const stdinPayload = stdin ?? "";
  const baseArgs = useResume ? (backend.resumeArgs ?? backend.args ?? []) : (backend.args ?? []);
  const resolvedArgs = useResume
    ? baseArgs.map((entry) => entry.replaceAll("{sessionId}", cliSessionIdToSend ?? ""))
    : baseArgs;
  const args = buildCliArgs({
    backend,
    baseArgs: resolvedArgs,
    modelId: normalizedModel,
    sessionId: cliSessionIdToSend,
    systemPrompt: systemPromptArg,
    imagePaths,
    promptArg: argsPrompt,
    useResume,
  });

  const serialize = backend.serialize ?? true;
  const queueKey = serialize ? backendResolved.id : `${backendResolved.id}:${params.runId}`;
  const isCodexBackend = backendResolved.id === "codex-cli";
  const maxBenignRetries = isCodexBackend ? 1 : 0;

  try {
    const output = await enqueueCliRun(queueKey, async () => {
      for (let attempt = 0; attempt <= maxBenignRetries; attempt += 1) {
        log.info(
          `cli exec: provider=${params.provider} model=${normalizedModel} promptChars=${params.prompt.length}`,
        );
        const logOutputText = isTruthyEnvValue(process.env.OPENCLAW_CLAUDE_CLI_LOG_OUTPUT);
        if (logOutputText) {
          const logArgs: string[] = [];
          for (let i = 0; i < args.length; i += 1) {
            const arg = args[i] ?? "";
            if (arg === backend.systemPromptArg) {
              const systemPromptValue = args[i + 1] ?? "";
              logArgs.push(arg, `<systemPrompt:${systemPromptValue.length} chars>`);
              i += 1;
              continue;
            }
            if (arg === backend.sessionArg) {
              logArgs.push(arg, args[i + 1] ?? "");
              i += 1;
              continue;
            }
            if (arg === backend.modelArg) {
              logArgs.push(arg, args[i + 1] ?? "");
              i += 1;
              continue;
            }
            if (arg === backend.imageArg) {
              logArgs.push(arg, "<image>");
              i += 1;
              continue;
            }
            logArgs.push(arg);
          }
          if (argsPrompt) {
            const promptIndex = logArgs.indexOf(argsPrompt);
            if (promptIndex >= 0) {
              logArgs[promptIndex] = `<prompt:${argsPrompt.length} chars>`;
            }
          }
          log.info(`cli argv: ${backend.command} ${logArgs.join(" ")}`);
        }

        const env = (() => {
          const next = { ...process.env, ...backend.env };
          for (const key of backend.clearEnv ?? []) {
            delete next[key];
          }
          return next;
        })();

        // Cleanup suspended processes that have accumulated (regardless of sessionId)
        await cleanupSuspendedCliProcesses(backend);
        if (useResume && cliSessionIdToSend) {
          await cleanupResumeProcesses(backend, cliSessionIdToSend);
        }

        const result = await runCommandWithTimeout([backend.command, ...args], {
          timeoutMs: params.timeoutMs,
          cwd: workspaceDir,
          env,
          input: stdinPayload,
        });

        const stdout = result.stdout.trim();
        const stderr = result.stderr.trim();
        if (logOutputText) {
          if (stdout) {
            log.info(`cli stdout:\n${stdout}`);
          }
          if (stderr) {
            log.info(`cli stderr:\n${stderr}`);
          }
        }
        if (shouldLogVerbose()) {
          if (stdout) {
            log.debug(`cli stdout:\n${stdout}`);
          }
          if (stderr) {
            log.debug(`cli stderr:\n${stderr}`);
          }
        }

        const outputMode = useResume ? (backend.resumeOutput ?? backend.output) : backend.output;
        const parsedOutput =
          outputMode === "text"
            ? { text: stdout, sessionId: undefined }
            : outputMode === "jsonl"
              ? parseCliJsonl(stdout, backend)
              : parseCliJson(stdout, backend);
        const resolvedOutput = parsedOutput ?? { text: stdout };

        if (result.code === 0) {
          return resolvedOutput;
        }

        const benignCodexWarning = isCodexBackend && isCodexBenignWarningOnly(stderr);
        const hasMeaningfulText = Boolean(resolvedOutput.text?.trim());
        if (benignCodexWarning && hasMeaningfulText) {
          log.warn(
            `codex-cli exited with code ${result.code ?? "unknown"} but produced text output; accepting response`,
          );
          return resolvedOutput;
        }

        if (benignCodexWarning && attempt < maxBenignRetries) {
          log.warn(
            `codex-cli exited with benign warning-only stderr; retrying once (${attempt + 1}/${maxBenignRetries})`,
          );
          continue;
        }

        const err = stderr || stdout || "CLI failed.";
        const reason = classifyFailoverReason(err) ?? "unknown";
        const status = resolveFailoverStatus(reason);
        throw new FailoverError(err, {
          reason,
          provider: params.provider,
          model: modelId,
          status,
        });
      }
      throw new Error("CLI execution exhausted retries.");
    });

    const text = output.text?.trim();
    const payloads = text ? [{ text }] : undefined;

    return {
      payloads,
      meta: {
        durationMs: Date.now() - started,
        agentMeta: {
          sessionId: output.sessionId ?? sessionIdSent ?? params.sessionId ?? "",
          provider: params.provider,
          model: modelId,
          usage: output.usage,
        },
      },
    };
  } catch (err) {
    if (err instanceof FailoverError) {
      throw err;
    }
    const message = err instanceof Error ? err.message : String(err);
    if (isFailoverErrorMessage(message)) {
      const reason = classifyFailoverReason(message) ?? "unknown";
      const status = resolveFailoverStatus(reason);
      throw new FailoverError(message, {
        reason,
        provider: params.provider,
        model: modelId,
        status,
      });
    }
    throw err;
  } finally {
    if (cleanupImages) {
      await cleanupImages();
    }
  }
}

export async function runClaudeCliAgent(params: {
  sessionId: string;
  sessionKey?: string;
  agentId?: string;
  sessionFile: string;
  workspaceDir: string;
  config?: OpenClawConfig;
  prompt: string;
  provider?: string;
  model?: string;
  thinkLevel?: ThinkLevel;
  timeoutMs: number;
  runId: string;
  extraSystemPrompt?: string;
  ownerNumbers?: string[];
  claudeSessionId?: string;
  images?: ImageContent[];
  isHeartbeat?: boolean;
}): Promise<EmbeddedPiRunResult> {
  return runCliAgent({
    sessionId: params.sessionId,
    sessionKey: params.sessionKey,
    agentId: params.agentId,
    sessionFile: params.sessionFile,
    workspaceDir: params.workspaceDir,
    config: params.config,
    prompt: params.prompt,
    provider: params.provider ?? "claude-cli",
    model: params.model ?? "opus",
    thinkLevel: params.thinkLevel,
    timeoutMs: params.timeoutMs,
    runId: params.runId,
    extraSystemPrompt: params.extraSystemPrompt,
    ownerNumbers: params.ownerNumbers,
    cliSessionId: params.claudeSessionId,
    images: params.images,
    isHeartbeat: params.isHeartbeat,
  });
}
