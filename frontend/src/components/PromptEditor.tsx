import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type PromptItem } from "../api";
import { Btn, Card, ErrorBanner, Spinner } from "../ui";

const LABELS: Record<string, string> = {
  screen: "Screening prompt",
  affiliations: "Affiliations prompt",
};

const HINTS: Record<string, string> = {
  screen:
    "Instructions sent to the LLM that judges each paper for frontier-AI-safety and categorizes it. Keep the {{title}}, {{categories}}, {{abstract}} and {{extra}} placeholders — they are filled in per paper.",
  affiliations:
    "Instructions sent to the LLM that extracts author affiliations and the paper-level mainland-China verdict. Keep the {{paper_text}} and {{author_names}} placeholders — they are filled in per paper.",
};

// Show the screening prompt first (it's the one most often tuned), then the rest.
const ORDER: Record<string, number> = { screen: 0, affiliations: 1 };

function PromptCard({ item }: { item: PromptItem }) {
  const qc = useQueryClient();
  const [text, setText] = useState(item.text);
  const [savedFlash, setSavedFlash] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const dirty = text !== item.text;
  const label = LABELS[item.name] ?? item.name;
  const hint = HINTS[item.name];

  const save = useMutation({
    mutationFn: () => api.savePrompt(item.name, text),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["prompts"] });
      setSavedFlash(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setSavedFlash(false), 3000);
    },
  });

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-zinc-200">{label}</span>
        <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">v{item.version}</span>
        {dirty && <span className="text-xs text-amber-400">unsaved changes</span>}
        {savedFlash && <span className="text-xs text-emerald-400">Saved — active for new runs.</span>}
      </div>
      {hint && <p className="text-xs text-zinc-500">{hint}</p>}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        className="h-80 w-full resize-y rounded-lg border border-zinc-700 bg-zinc-950 p-3 font-mono text-xs leading-relaxed text-zinc-100 focus:border-emerald-500 focus:outline-none"
      />
      <div className="flex items-center gap-3">
        <Btn variant="primary" onClick={() => save.mutate()} disabled={save.isPending || !dirty}>
          {save.isPending ? "Saving…" : `Save ${label}`}
        </Btn>
        <button
          className="text-xs text-zinc-500 hover:text-zinc-300"
          onClick={() => setText(item.text)}
          disabled={!dirty}
        >
          revert
        </button>
      </div>
      {save.isError && <ErrorBanner error={save.error} />}
    </div>
  );
}

export default function PromptEditor() {
  const { data, isLoading, error } = useQuery({ queryKey: ["prompts"], queryFn: api.prompts });

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner error={error} />;

  const items = [...(data?.items ?? [])].sort(
    (a, b) => (ORDER[a.name] ?? 99) - (ORDER[b.name] ?? 99),
  );

  return (
    <Card title="LLM prompts">
      <p className="mb-3 text-xs text-zinc-500">
        The exact instructions sent to the LLM for each pipeline stage. Saving creates a new version;
        the latest version is used automatically by new runs (and shown in each paper's call history).
      </p>
      <div className="flex flex-col gap-6">
        {items.map((item) => (
          <PromptCard key={item.name} item={item} />
        ))}
      </div>
    </Card>
  );
}
