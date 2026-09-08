/*
 * Tests for language detection helpers.
 *
 * Browser-free — operates on plain text only.
 */

import { describe, it, expect } from 'vitest';
import { dominantScript, looksLikeTargetLanguage } from '../src/core/lang';

describe('dominantScript', () => {
  it('should detect CJK text', () => {
    expect(dominantScript('你好世界')).toBe('cjk');
    expect(dominantScript('こんにちは')).toBe('cjk');
    expect(dominantScript('안녕하세요')).toBe('cjk');
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

  it('should return false for very short text', () => {
    expect(looksLikeTargetLanguage('Hi', 'English')).toBe(false);
  });

  it('should return false for unknown target languages', () => {
    expect(looksLikeTargetLanguage('Hello', 'Klingon')).toBe(false);
  });
});
