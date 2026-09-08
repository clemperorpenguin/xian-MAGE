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
 * Language detection helpers for segmentation.
 *
 * Uses a simple script-block histogram to classify text as CJK, Cyrillic,
 * Arabic, Latin, etc. — cheap enough to run on every paragraph, no model call.
 */

/** Unicode script ranges for common language families. */
const SCRIPTS = {
  cjk: [/[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]/, /[\u3040-\u309f]/, /[\uac00-\ud7af]/],
  cyrillic: [/[\u0400-\u04ff]/, /[\u0500-\u052f]/],
  arabic: [/[\u0600-\u06ff]/, /[\u0750-\u077f]/, /[\ufb50-\ufdff]/, /[\ufe70-\ufeff]/],
  latin: [/[\u0000-\u024f]/],
};

export type ScriptClass = 'cjk' | 'cyrillic' | 'arabic' | 'latin' | 'other';

/**
 * Classify a block of text by dominant script.
 */
export function dominantScript(text: string): ScriptClass {
  const counts: Record<string, number> = { cjk: 0, cyrillic: 0, arabic: 0, latin: 0, other: 0 };

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (SCRIPTS.cjk.some(r => r.test(ch))) counts.cjk++;
    else if (SCRIPTS.cyrillic.some(r => r.test(ch))) counts.cyrillic++;
    else if (SCRIPTS.arabic.some(r => r.test(ch))) counts.arabic++;
    else if (SCRIPTS.latin.some(r => r.test(ch))) counts.latin++;
    else counts.other++;
  }

  let maxCount = 0;
  let maxScript: ScriptClass = 'other';
  for (const [script, count] of Object.entries(counts)) {
    if (count > maxCount) {
      maxCount = count;
      maxScript = script as ScriptClass;
    }
  }

  return maxScript;
}

/**
 * Quick check: does this text look like it's already in the target language?
 *
 * Uses the dominant script heuristic — if the text's script matches the
 * target language's expected script, it's likely already in that language.
 * This is intentionally cheap and approximate; it's only used to skip
 * segments that are already in the target language on bilingual pages.
 */
export function looksLikeTargetLanguage(
  text: string,
  targetLang: string,
): boolean {
  if (text.length < 10) return false; // too short to decide

  const script = dominantScript(text);

  // Map target language names to expected scripts
  const targetScripts: Record<string, ScriptClass[]> = {
    'english': ['latin'],
    'japanese': ['cjk'],
    'chinese': ['cjk'],
    'korean': ['cjk'],
    'russian': ['cyrillic'],
    'ukrainian': ['cyrillic'],
    'arabic': ['arabic'],
    'french': ['latin'],
    'spanish': ['latin'],
    'german': ['latin'],
    'italian': ['latin'],
    'portuguese': ['latin'],
    'dutch': ['latin'],
  };

  const expected = targetScripts[targetLang.toLowerCase()];
  if (!expected) return false;

  return expected.includes(script);
}
