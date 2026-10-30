"""Строгая проверка ответов MCQ и допуск без регрессии качества."""

import json
import math


def _unique_by_id(items, name):
    if not isinstance(items, list) or not items:
        raise ValueError(f'{name}: нужен непустой список')
    result = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']:
            raise ValueError(f'{name}: нужен строковый id')
        if item['id'] in result:
            raise ValueError(f'{name}: повтор id {item["id"]}')
        result[item['id']] = item
    return result


def _counts(items):
    n = len(items)
    correct = sum(item['correct'] for item in items)
    valid = sum(item['valid'] for item in items)
    errors = sum(item['error'] is not None for item in items)
    return dict(n=n, correct=correct, valid=valid, errors=errors,
                accuracy=correct / n, format_rate=valid / n)


def _slices(items):
    names = sorted({s for item in items for s in item['slices']})
    return {name: _counts([item for item in items if name in item['slices']]) for name in names}


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('JSON содержит повторяющийся ключ')
        result[key] = value
    return result


def _bad_constant(value):
    raise ValueError(f'Недопустимая JSON-константа {value}')


def score(rows, outputs):
    """Верните overall, slices и per_item. Не удаляйте плохие ответы из знаменателя.

    Строгий ответ: JSON с единственным строковым полем answer из choices.
    outputs: [{id, raw, error, latency_seconds}, ...].
    В overall и каждом срезе: n, correct, valid, errors, accuracy, format_rate.
    В per_item: id, raw, parsed, valid, correct, error, slices.
    Несовпадающие/дублирующиеся id и пустой набор должны вызвать ValueError.
    """
    tasks = _unique_by_id(rows, 'Задания')
    answers = _unique_by_id(outputs, 'Ответы')
    if tasks.keys() != answers.keys():
        raise ValueError('ID заданий и ответов не совпадают')
    per_item = []
    for row in rows:
        choices, slices = row.get('choices'), row.get('slices')
        if (not isinstance(choices, list) or not choices
                or any(not isinstance(s, str) for s in choices)
                or len(choices) != len(set(choices)) or row.get('expected') not in choices):
            raise ValueError(f'{row["id"]}: некорректные choices/expected')
        if (not isinstance(slices, list) or not slices
                or any(not isinstance(s, str) or not s for s in slices)
                or len(slices) != len(set(slices))):
            raise ValueError(f'{row["id"]}: некорректные slices')
        answer = answers[row['id']]
        if 'raw' not in answer or 'error' not in answer:
            raise ValueError(f'{row["id"]}: отсутствует raw/error')
        raw, error = answer['raw'], answer['error']
        if error is not None and (not isinstance(error, str) or not error):
            raise ValueError('error должен быть None или непустой строкой')
        parsed, valid, correct = None, False, False
        if error is None and isinstance(raw, str):
            try:
                parsed = json.loads(raw, object_pairs_hook=_json_object, parse_constant=_bad_constant)
                valid = (isinstance(parsed, dict) and set(parsed) == {'answer'}
                         and isinstance(parsed['answer'], str) and parsed['answer'] in choices)
                correct = valid and parsed['answer'] == row['expected']
            except (ValueError, TypeError, RecursionError):
                parsed = None
        per_item.append(dict(id=row['id'], raw=raw, parsed=parsed, valid=valid,
                             correct=correct, error=error, slices=list(slices)))
    return dict(overall=_counts(per_item), slices=_slices(per_item), per_item=per_item)


def _validate_stats(actual, expected, name):
    if not isinstance(actual, dict):
        raise ValueError(f'{name}: нет метрик')
    for key in ('n', 'correct', 'valid', 'errors'):
        if type(actual.get(key)) is not int or actual[key] != expected[key]:
            raise ValueError(f'{name}: {key} не соответствует per_item')
    for key in ('accuracy', 'format_rate'):
        value = actual.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not math.isclose(value, expected[key], rel_tol=0, abs_tol=1e-12)):
            raise ValueError(f'{name}: некорректная {key}')


def _validate_score(report, name, minimum):
    if not isinstance(report, dict):
        raise ValueError(f'{name}: отчёт отсутствует')
    items = report.get('per_item')
    indexed = _unique_by_id(items, name)
    if len(items) < minimum:
        raise ValueError(f'{name}: минимум {minimum} примеров')
    for item in items:
        if type(item.get('valid')) is not bool or type(item.get('correct')) is not bool:
            raise ValueError(f'{name}: valid/correct должны быть bool')
        if item['correct'] and not item['valid']:
            raise ValueError(f'{name}: правильный ответ не может быть невалидным')
        if 'raw' not in item or 'parsed' not in item or 'error' not in item:
            raise ValueError(f'{name}: неполный per_item')
        if item['error'] is not None:
            if not isinstance(item['error'], str) or not item['error']:
                raise ValueError(f'{name}: некорректная ошибка')
            if item['valid'] or item['correct']:
                raise ValueError(f'{name}: ошибка генерации засчитана как ответ')
        names = item.get('slices')
        if (not isinstance(names, list) or not names
                or any(not isinstance(s, str) or not s for s in names)
                or len(names) != len(set(names))):
            raise ValueError(f'{name}: неверные срезы per_item')
    overall, slices = _counts(items), _slices(items)
    _validate_stats(report.get('overall'), overall, name)
    if not isinstance(report.get('slices'), dict) or report['slices'].keys() != slices.keys():
        raise ValueError(f'{name}: неполный набор срезов')
    for key, expected in slices.items():
        _validate_stats(report['slices'][key], expected, f'{name}/{key}')
    if overall['errors']:
        raise ValueError(f'{name}: ошибки генерации ({overall["errors"]})')
    return indexed


def _matching_items(baseline, candidate, name):
    if baseline.keys() != candidate.keys():
        raise ValueError(f'{name}: отличаются id')
    if any(set(baseline[i]['slices']) != set(candidate[i]['slices']) for i in baseline):
        raise ValueError(f'{name}: отличаются срезы вопросов')


def quality_gate(baseline, candidate, critical_slices):
    """Верните {passed: True, ...} или вызовите ValueError с причиной отказа.

    Проверьте совместимость протокола/набора/baseline, метрики и counts,
    все id и срезы, общую accuracy/format_rate, критические срезы и behavior.
    Missing, NaN, пустой набор и ошибки генерации означают отказ.
    Пороги задаются до измерения; учебный допуск регрессии равен нулю.
    """
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        raise ValueError('Отсутствует baseline/candidate')
    for key in ('protocol_sha256', 'golden_sha256', 'baseline_spec_sha256'):
        if (not isinstance(baseline.get(key), str) or not baseline[key]
                or baseline[key] != candidate.get(key)):
            raise ValueError(f'Несовместимый или отсутствующий {key}')
    for name, report in [('baseline', baseline), ('candidate', candidate)]:
        if report.get('status') != 'complete':
            raise ValueError(f'{name}: оценка не завершена')
        model = report.get('model')
        if not isinstance(model, dict) or not isinstance(model.get('kind'), str) or not model['kind']:
            raise ValueError(f'{name}: не указана конкретная модель')
        if model['kind'] == 'base' and (not isinstance(model.get('name'), str) or not model['name']
                                      or not isinstance(model.get('revision'), str)
                                      or len(model['revision']) != 40):
            raise ValueError(f'{name}: база не закреплена ревизией')
        if model['kind'] == 'adapter' and any(not model.get(k) for k in ('name', 'version', 'run_id', 'uri')):
            raise ValueError(f'{name}: не закреплена версия адаптера')
    a = _validate_score(baseline, 'baseline', 50)
    b = _validate_score(candidate, 'candidate', 50)
    _matching_items(a, b, 'golden')
    if len(baseline['slices']) < 3:
        raise ValueError('Golden: нужны минимум три среза')
    if (not isinstance(critical_slices, list) or not critical_slices
            or any(not isinstance(s, str) or not s for s in critical_slices)
            or len(critical_slices) != len(set(critical_slices))):
        raise ValueError('Нужно заранее задать критические срезы')
    if not set(critical_slices) <= baseline['slices'].keys():
        raise ValueError('Критический срез отсутствует')
    if baseline['slices'].keys() != candidate['slices'].keys():
        raise ValueError('Отличаются имена срезов')
    for name in baseline['slices']:
        if baseline['slices'][name]['n'] != candidate['slices'][name]['n']:
            raise ValueError(f'Отличается размер среза {name}')
    for key in ('accuracy', 'format_rate'):
        if candidate['overall'][key] < baseline['overall'][key]:
            raise ValueError(f'Регрессия общей {key}')
    for name in critical_slices:
        if candidate['slices'][name]['accuracy'] < baseline['slices'][name]['accuracy']:
            raise ValueError(f'Регрессия критического среза {name}')
    ba = _validate_score(baseline.get('behavioral'), 'baseline/behavioral', 3)
    bb = _validate_score(candidate.get('behavioral'), 'candidate/behavioral', 3)
    _matching_items(ba, bb, 'behavioral')
    behavior = candidate['behavioral']['overall']
    if behavior['correct'] != behavior['n'] or behavior['valid'] != behavior['n']:
        raise ValueError('Обязательные behavioral-кейсы кандидата не прошли')
    return dict(passed=True, protocol_sha256=candidate['protocol_sha256'],
                golden_sha256=candidate['golden_sha256'], model=candidate['model'],
                baseline=baseline['overall'], candidate=candidate['overall'],
                critical_slices=list(critical_slices), behavioral_passed=behavior['n'],
                allowed_regression=0)
