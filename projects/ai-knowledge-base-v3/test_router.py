"""Comprehensive test for router module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def test_import():
    """Test module import."""
    print('=== Test 1: Module Import ===')
    try:
        from patterns import route, detect_intent_by_keywords
        print('[OK] patterns module imported')
        return True
    except Exception as e:
        print(f'[FAIL] {e}')
        return False


def test_keyword_detection():
    """Test keyword-based intent detection."""
    print('\n=== Test 2: Keyword Detection ===')
    from patterns import detect_intent_by_keywords
    
    test_cases = [
        ('github trending', 'github_search'),
        ('knowledge base', 'knowledge_query'),
        ('help me', None),
        ('开源 项目', 'github_search'),
        ('查找 文章', 'knowledge_query'),
    ]
    
    passed = 0
    for query, expected in test_cases:
        result = detect_intent_by_keywords(query)
        status = 'OK' if result == expected else 'FAIL'
        print(f'[{status}] "{query}" -> {result} (expected: {expected})')
        if status == 'OK':
            passed += 1
    
    return passed == len(test_cases)


def test_routing():
    """Test the routing functionality."""
    print('\n=== Test 3: Routing ===')
    from patterns import route
    
    queries = [
        'Find LLM articles',
        'How does AI work?',
    ]
    
    for query in queries:
        try:
            response = route(query)
            preview = response[:60].replace('\n', ' ')
            print(f'[OK] "{query}" -> {preview}...')
        except Exception as e:
            print(f'[FAIL] "{query}" error: {e}')
            return False
    
    return True


def main():
    """Run all tests."""
    print('\n' + '=' * 70)
    print('Router Pattern - Comprehensive Test Suite')
    print('=' * 70)
    
    results = [
        test_import(),
        test_keyword_detection(),
        test_routing(),
    ]
    
    print('\n' + '=' * 70)
    if all(results):
        print('Result: ALL TESTS PASSED [OK]')
    else:
        print('Result: SOME TESTS FAILED [FAIL]')
    print('=' * 70)
    
    return 0 if all(results) else 1


if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
