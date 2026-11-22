// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { addToken, hasToken, hitParts, lastToken, operatorCompletions, removeToken, replaceLastToken, tokens } from './searchQuery.js';

describe('search query editing', () => {
  it('splits on spaces outside quotes', () => {
    expect(tokens('from:"Ann Lee" "two words" x')).toEqual(['from:"Ann Lee"', '"two words"', 'x']);
  });
  it('toggles filters', () => {
    expect(addToken('invoice', 'is:unread')).toBe('invoice is:unread');
    expect(hasToken('invoice is:unread', 'IS:UNREAD')).toBe(true);
    expect(removeToken('invoice is:unread', 'is:unread')).toBe('invoice');
    expect(addToken('x newer_than:7d', 'newer_than:30d')).toBe('x newer_than:30d');
    expect(addToken('x in:inbox', 'in:anywhere')).toBe('x in:anywhere');
  });
  it('completes the word being typed', () => {
    expect(lastToken('invoice fro')).toBe('fro');
    expect(lastToken('invoice ')).toBe('');
    expect(replaceLastToken('invoice fro', 'from:')).toBe('invoice from:');
    expect(replaceLastToken('invoice from:al', 'from:alice@x.test')).toBe('invoice from:alice@x.test ');
    expect(replaceLastToken('', 'has:pdf')).toBe('has:pdf ');
    expect(operatorCompletions('has:p').map((o) => o.text)).toEqual(['has:pdf', 'has:presentation']);
    expect(operatorCompletions('x')).toEqual([]);
  });
  it('turns match markers into safe parts', () => {
    expect(hitParts('the \x02invoice\x03 for \x02March\x03…')).toEqual([
      { text: 'the ', hit: false }, { text: 'invoice', hit: true }, { text: ' for ', hit: false },
      { text: 'March', hit: true }, { text: '…', hit: false },
    ]);
    expect(hitParts('<b>no html</b>')).toEqual([{ text: '<b>no html</b>', hit: false }]);
  });
});
