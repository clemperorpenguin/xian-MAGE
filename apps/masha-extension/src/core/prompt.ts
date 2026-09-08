/*
 * Masha — Browser extension selection translator.
 * Copyright (C) 2026  Clementine Pendragon <clem@pendragon.systems>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 * Contact: clem@pendragon.systems (Clementine Pendragon, c/o Xian Project Development)
 */

/*
 * Browser-free core — see core/constants.ts.
 *
 * Text-translation prompt. Mirrors the framing of MAGE's
 * ``Pipeline.create_prompt`` (packages/xian-vl/src/xian/pipeline.py): terse,
 * "Direct translation into {target}", output ONLY the translation, keep
 * reasoning brief, optional style terms. The OCR/3-part-layout rules from MAGE
 * are dropped here because this path translates text, not images. The key
 * addition over Google Translate is the page-context block, fed strictly as
 * reference so the model disambiguates meaning, pronouns, and terminology.
 */

import { MAX_CONTEXT_CHARS } from './constants';

export interface ChatMessage {
  role: 'system' | 'user';
  content: string;
}

export interface PromptOptions {
  /** The exact text the user selected — the only thing to be translated. */
  selection: string;
  /** Surrounding page text (title + section), reference only. May be empty. */
  context?: string;
  /** ``"Auto"`` to let the model detect, or an explicit language name. */
  sourceLang: string;
  targetLang: string;
  /** Optional stylistic register terms (mirrors MAGE ``styles``). */
  styles?: string[];
  /** Source term → required translation. Enforced in the prompt. */
  glossary?: Record<string, string>;
}

/** Wrap a segment id in the marker the batch protocol keys on. */
export function segmentMarker(id: string): string {
  return `<<<MASHA_SEGMENT_${id}>>>`;
}

/** Collapse whitespace and clamp context to the configured budget. */
export function clampContext(context: string, max: number = MAX_CONTEXT_CHARS): string {
  const collapsed = context.replace(/\s+/g, ' ').trim();
  return collapsed.length > max ? collapsed.slice(0, max) + '…' : collapsed;
}

/** Rendered glossary block, or '' when there is nothing to enforce. */
function glossaryBlock(glossary?: Record<string, string>): string {
  const entries = Object.entries(glossary ?? {});
  if (entries.length === 0) return '';
  return entries.map(([term, translation]) => `- ${term} → ${translation}`).join('\n');
}

/** The rules both the selection and the batch prompt share. */
function commonRules(opts: PromptOptions, hasGlossary: boolean): string {
  const styleContext =
    opts.styles && opts.styles.length > 0
      ? ` Optionally use ${opts.styles.join(', ')} terms if it does not compromise accuracy.`
      : '';

  return (
    `- Produce a direct, faithful translation that preserves the original tone, register, and inline formatting.\n` +
    `- Use the PAGE CONTEXT ONLY as reference to disambiguate meaning, pronouns, gender, honorifics, and terminology. ` +
    `Do NOT translate the context.\n` +
    (hasGlossary
      ? `- The GLOSSARY is binding: render each listed term exactly as given, inflected to fit the sentence.\n`
      : '') +
    `- If the text is already in ${opts.targetLang}, return it unchanged.${styleContext}\n` +
    `- Keep any reasoning extremely brief; do not narrate your process.`
  );
}

/** ``"X → Y"`` fragment, empty when the source language is auto-detected. */
function langClause(opts: PromptOptions): string {
  return opts.sourceLang && opts.sourceLang !== 'Auto' ? ` from ${opts.sourceLang}` : '';
}

/** Assemble the user message: optional context, optional glossary, then the payload. */
function userMessage(opts: PromptOptions, payloadLabel: string): string {
  const parts: string[] = [];

  const context = opts.context ? clampContext(opts.context) : '';
  if (context) {
    parts.push(`PAGE CONTEXT (reference only — do not translate):\n${context}`);
  }

  const glossary = glossaryBlock(opts.glossary);
  if (glossary) {
    parts.push(`GLOSSARY (binding terminology):\n${glossary}`);
  }

  parts.push(`${payloadLabel}\n${opts.selection}`);
  return parts.join('\n\n');
}

/** Build the OpenAI-style chat messages for a selection translation. */
export function buildTranslationMessages(opts: PromptOptions): ChatMessage[] {
  const fromClause = langClause(opts);
  const hasGlossary = Object.keys(opts.glossary ?? {}).length > 0;

  const systemPrompt =
    `You are MASHA, a highly precise${fromClause ? ` ${opts.sourceLang} →` : ''} ${opts.targetLang} translation engine.\n` +
    `Translate the user's SELECTION${fromClause} into ${opts.targetLang}.\n` +
    `RULES:\n` +
    `- Output ONLY the translation. No quotes, no romanization, no explanations, no conversational filler.\n` +
    `- Translate ONLY the text under SELECTION.\n` +
    commonRules(opts, hasGlossary);

  return [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userMessage(opts, 'SELECTION (translate this):') },
  ];
}

/**
 * Build the chat messages for a *batch* of page segments.
 *
 * ``opts.selection`` is the marker-delimited batch body. The markers are the
 * whole point of the batch protocol — the response is matched back to segments
 * by marker, never by position — so the rules that keep them intact have to be
 * in the prompt. A prompt that only says "output ONLY the translation" gets a
 * marker-free answer back, and every segment in the batch fails to parse.
 */
export function buildBatchTranslationMessages(opts: PromptOptions): ChatMessage[] {
  const fromClause = langClause(opts);
  const hasGlossary = Object.keys(opts.glossary ?? {}).length > 0;

  const systemPrompt =
    `You are MASHA, a highly precise${fromClause ? ` ${opts.sourceLang} →` : ''} ${opts.targetLang} translation engine.\n` +
    `The user's message holds several independent passages from one web page. Each passage is\n` +
    `enclosed by a matching pair of identical marker lines of the form <<<MASHA_SEGMENT_id>>>.\n` +
    `Translate every passage${fromClause} into ${opts.targetLang}.\n` +
    `RULES:\n` +
    `- Reproduce every marker line EXACTLY as it appears, in the same order, and place each\n` +
    `  passage's translation between that passage's own opening and closing markers.\n` +
    `- Never translate, renumber, reword, merge, drop, or reformat a marker line.\n` +
    `- Output ONLY marker lines and translations. No quotes, no romanization, no explanations,\n` +
    `  no conversational filler, no commentary about the markers.\n` +
    `- Translate each passage on its own; the passages are separate blocks of the page.\n` +
    commonRules(opts, hasGlossary);

  return [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userMessage(opts, 'PASSAGES (translate each, keeping its markers):') },
  ];
}
