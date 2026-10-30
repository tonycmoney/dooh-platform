import 'package:dooh_player/src/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('manifest carries the Trillboards fallback URL', () {
    final manifest = Manifest.fromJson({
      'version': 'v2',
      'loop_id': null,
      'loop_name': null,
      'items': <dynamic>[],
      'fallback_url': 'https://screen.trillboards.com?fp=P_abc123',
    });
    expect(manifest.fallbackUrl, 'https://screen.trillboards.com?fp=P_abc123');
    final again = Manifest.fromJson(manifest.toJson());
    expect(again.fallbackUrl, manifest.fallbackUrl);
  });

  test('older servers without fallback_url still parse', () {
    final manifest = Manifest.fromJson({
      'version': 'v1',
      'items': <dynamic>[],
    });
    expect(manifest.fallbackUrl, isNull);
  });
}
