import 'package:flutter_test/flutter_test.dart';
import 'package:securelinkdb/word_error_rate.dart';

void main() {
  test(
    'matches evaluation normalization for case, ñ, punctuation and hyphens',
    () {
      final result = scoreWordErrorRate(
        "  Niño, nag-aaral  'YAN! ",
        "NIÑO NAG AARAL 'yan",
      )!;
      expect(result.edits, 0);
      expect(result.referenceWords, 4);
      expect(result.percentage, 0);
      expect(result.needsReview, isFalse);
    },
  );

  test('blank and unscoreable references have no WER', () {
    expect(scoreWordErrorRate('   ', 'may salita'), isNull);
    expect(scoreWordErrorRate('… —!?', 'may salita'), isNull);
  });

  test('exactly 50 percent is not flagged', () {
    final result = scoreWordErrorRate('one two', 'one three')!;
    expect(result.edits, 1);
    expect(result.percentage, 50);
    expect(result.needsReview, isFalse);
  });

  test('greater than 50 percent is flagged', () {
    final result = scoreWordErrorRate('one two three', 'one')!;
    expect(result.referenceWords, 3);
    expect(result.edits, 2);
    expect(result.needsReview, isTrue);
  });

  test('insertions can produce WER above 100 percent', () {
    final result = scoreWordErrorRate('one', 'one two three')!;
    expect(result.edits, 2);
    expect(result.percentage, 200);
    expect(result.needsReview, isTrue);
  });
}
