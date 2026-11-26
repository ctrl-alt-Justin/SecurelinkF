/// Offline word-error scoring equivalent to eval/metrics.py for a typed reference.
class WordErrorRate {
  const WordErrorRate(this.edits, this.referenceWords);

  final int edits;
  final int referenceWords;

  double get percentage => edits * 100 / referenceWords;
  bool get needsReview => edits * 2 > referenceWords;
}

final _wordSeparator = RegExp(r"[^a-z0-9ñ']+");

List<String> _tokens(String text) => text
    .replaceAll('\u0130', 'i\u0307')
    .toLowerCase()
    .split(_wordSeparator)
    .where((token) => token.isNotEmpty)
    .toList();

WordErrorRate? scoreWordErrorRate(String reference, String hypothesis) {
  final expected = _tokens(reference);
  if (expected.isEmpty) return null;
  final actual = _tokens(hypothesis);
  var previous = List.generate(actual.length + 1, (index) => index);

  for (var row = 1; row <= expected.length; row++) {
    final next = List<int>.filled(actual.length + 1, row);
    for (var col = 1; col <= actual.length; col++) {
      final substitution =
          previous[col - 1] + (expected[row - 1] == actual[col - 1] ? 0 : 1);
      final deletion = previous[col] + 1;
      final insertion = next[col - 1] + 1;
      final skip = deletion < insertion ? deletion : insertion;
      next[col] = substitution < skip ? substitution : skip;
    }
    previous = next;
  }
  return WordErrorRate(previous.last, expected.length);
}
