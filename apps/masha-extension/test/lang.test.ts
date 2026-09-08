/*
 * Tests for language detection helpers.
 *
 * Browser-free — operates on plain text only.
 */

import { describe, it, expect } from 'vitest';
import { dominantScript, looksLikeTargetLanguage, scriptCounts } from '../src/core/lang';

describe('dominantScript', () => {
  it('should tell the CJK scripts apart', () => {
    expect(dominantScript('你好世界')).toBe('han');
    expect(dominantScript('こんにちは')).toBe('kana');
    expect(dominantScript('안녕하세요')).toBe('hangul');
  });

  it('should detect katakana', () => {
    // Katakana was missing from the script table, so loanword-heavy Japanese
    // — product names, menus, technical writing — classified as 'other'.
    expect(dominantScript('コンピュータープログラム')).toBe('kana');
    expect(dominantScript('ソフトウェア')).toBe('kana');
    expect(scriptCounts('コンピューター').other).toBe(0);
  });

  it('should detect Latin text', () => {
    expect(dominantScript('Hello world')).toBe('latin');
    expect(dominantScript('Bonjour le monde')).toBe('latin');
  });

  it('should detect Cyrillic text', () => {
    expect(dominantScript('Привет мир')).toBe('cyrillic');
  });

  it('should detect Arabic text', () => {
    expect(dominantScript('مرحبا بالعالم')).toBe('arabic');
  });
});

describe('looksLikeTargetLanguage', () => {
  it('should return true when Latin text is already English', () => {
    expect(looksLikeTargetLanguage('Hello world', 'English')).toBe(true);
    expect(looksLikeTargetLanguage('This is a test', 'English')).toBe(true);
  });

  it('should return false when CJK text is checked against English', () => {
    expect(looksLikeTargetLanguage('你好世界', 'English')).toBe(false);
  });

  it('should return true when CJK text is checked against Chinese', () => {
    expect(looksLikeTargetLanguage('你好世界，这是一个测试句子', 'Chinese')).toBe(true);
  });

  it('should not call Chinese text Japanese, or the reverse', () => {
    // Han is shared, so one CJK bucket meant a Chinese page translated into
    // Japanese was skipped paragraph by paragraph as "already in target".
    const chinese = '你好世界，这是一个测试句子';
    const japanese = 'これはテストの文章です。よろしくお願いします。';

    expect(looksLikeTargetLanguage(chinese, 'Japanese')).toBe(false);
    expect(looksLikeTargetLanguage(japanese, 'Chinese')).toBe(false);
    expect(looksLikeTargetLanguage(japanese, 'Japanese')).toBe(true);
  });

  it('should recognise kanji-heavy Japanese by its kana', () => {
    expect(looksLikeTargetLanguage('東京都の天気は晴れです。明日も晴れるでしょう。', 'Japanese')).toBe(true);
  });

  it('should not confuse Korean with the other CJK languages', () => {
    const korean = '안녕하세요, 이것은 테스트 문장입니다.';
    expect(looksLikeTargetLanguage(korean, 'Korean')).toBe(true);
    expect(looksLikeTargetLanguage(korean, 'Chinese')).toBe(false);
    expect(looksLikeTargetLanguage(korean, 'Japanese')).toBe(false);
  });

  it('should return false for very short text', () => {
    expect(looksLikeTargetLanguage('Hi', 'English')).toBe(false);
  });

  it('should return false for unknown target languages', () => {
    expect(looksLikeTargetLanguage('Hello', 'Klingon')).toBe(false);
  });
});
