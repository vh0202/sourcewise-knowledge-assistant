import { ArrowUp, FolderOpen } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { Tooltip } from "../../components/overlays";
import { Kbd } from "../../components/ui";
import type { Collection } from "../../lib/types";

interface ComposerProps {
  disabled: boolean;
  collections: Collection[];
  scope: number | null;
  onScopeChange: (collectionId: number | null) => void;
  onSend: (question: string) => void;
}

const MAX_LENGTH = 2000;

/** The question box: Enter sends, Shift+Enter adds a line, and the search can be limited to one collection. */
export function Composer({ disabled, collections, scope, onScopeChange, onSend }: ComposerProps) {
  const [value, setValue] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);

  // Grow with the content, up to about six lines.
  useEffect(() => {
    const element = textarea.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 168)}px`;
  }, [value]);

  useEffect(() => {
    if (!disabled) textarea.current?.focus({ preventScroll: true });
  }, [disabled]);

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    const question = value.trim();
    if (!question || disabled) return;
    onSend(question);
    setValue("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const canSend = !disabled && value.trim().length > 0;

  return (
    <form onSubmit={submit} className="relative mx-auto w-full max-w-[46rem] px-4 pb-3 sm:px-6">
      {/* The messages fade out behind the composer instead of being cut off by a line. */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-8 h-8 bg-linear-to-b from-transparent to-surface" />
      <div className="relative rounded-2xl bg-card shadow-composer transition-shadow duration-200 ease-standard focus-within:shadow-composer-focus">
        <label htmlFor="question" className="sr-only">
          Your question
        </label>
        <textarea
          id="question"
          ref={textarea}
          rows={1}
          value={value}
          maxLength={MAX_LENGTH}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask a question about your documents"
          className="block w-full resize-none bg-transparent px-4 pt-3.5 pb-1.5 text-md text-fg placeholder:text-fg-subtle focus:outline-none"
        />
        <div className="flex items-center gap-2 py-2 pr-2 pl-2.5">
          <label className="flex min-w-0 items-center gap-1.5 rounded-md py-0.5 pl-1.5 text-xs text-fg-subtle transition-colors duration-150 hover:bg-wash">
            <FolderOpen className="size-3.5 shrink-0" aria-hidden />
            <span className="sr-only">Search in</span>
            <select
              value={scope ?? ""}
              onChange={(event) => onScopeChange(event.target.value ? Number(event.target.value) : null)}
              className="min-w-0 cursor-pointer truncate rounded-md bg-transparent py-1 pr-6 pl-0.5 text-xs font-medium text-fg-muted [field-sizing:content]"
            >
              <option value="">All collections</option>
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>
                  {collection.name}
                </option>
              ))}
            </select>
          </label>
          <p aria-hidden className="ml-auto hidden items-center gap-1.5 text-xs text-fg-subtle md:flex">
            <Kbd>Enter</Kbd> to send
            <span className="text-fg-faint">·</span>
            <Kbd>Shift</Kbd>
            <Kbd>Enter</Kbd> for a new line
          </p>
          <Tooltip label="Send" shortcut="Enter">
            <button
              type="submit"
              disabled={!canSend}
              aria-label="Send question"
              className="ml-auto flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent bg-linear-to-b from-white/10 to-white/0 text-on-accent shadow-button transition-[background-color,box-shadow,opacity,transform] duration-150 ease-standard hover:bg-accent-hover active:translate-y-px disabled:pointer-events-none disabled:bg-wash-strong disabled:bg-none disabled:text-fg-faint disabled:shadow-none md:ml-1"
            >
              <ArrowUp className="size-4" aria-hidden />
            </button>
          </Tooltip>
        </div>
      </div>
      <p className="mt-2 text-center text-xs text-fg-subtle">
        Answers come only from the knowledge base. Check the cited source before acting on one.
      </p>
    </form>
  );
}
