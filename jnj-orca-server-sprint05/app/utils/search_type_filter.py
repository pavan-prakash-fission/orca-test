"""
BooleanSearchFilter provides utilities to convert boolean search queries
into SQLAlchemy filters. Supports AND, OR, NOT operators, wildcards '*',
and array columns. Invalid queries return `false()` to prevent unintended
results.
"""
import re
from typing import Union, Tuple, Dict, Optional

import boolean
from boolean import ParseError, Expression
from sqlalchemy import and_, or_, not_, func
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList
from sqlalchemy.sql.expression import true, false
from sqlalchemy.orm.attributes import InstrumentedAttribute


def sanitize_query(query: str) -> str:
    """
    Replace literal (non-grouping) parentheses with placeholders.
    
    """
    OPERATORS = {'AND', 'OR', 'NOT'}
    
    # Track which parentheses are grouping parentheses
    grouping_parens = set()
    stack = []  # Stack of (index, depth, is_grouping)
    depth = 0
    
    # First pass: identify grouping parentheses
    i = 0
    while i < len(query):
        ch = query[i]
        
        if ch == '(':
            # Look at context before the '('
            before = query[:i].rstrip()
            
            # Check if this opens a grouping context
            is_grouping = False
            
            if not before:  # Start of query
                is_grouping = True
            else:
                # Get the last token before this paren
                tokens = before.split()
                if tokens:
                    last_token = tokens[-1].upper()
                    # If preceded by operator, it's grouping
                    if last_token in OPERATORS:
                        is_grouping = True
                    # If preceded by another opening paren, it's grouping
                    elif before.endswith('('):
                        is_grouping = True
            
            # Look ahead to see if there are operators inside
            if not is_grouping:
                # Find matching closing paren
                temp_depth = 1
                j = i + 1
                inner_content = []
                while j < len(query) and temp_depth > 0:
                    if query[j] == '(':
                        temp_depth += 1
                    elif query[j] == ')':
                        temp_depth -= 1
                        if temp_depth == 0:
                            break
                    inner_content.append(query[j])
                    j += 1
                
                inner_str = ''.join(inner_content)
                # If inner content has operators at word boundaries, it's grouping
                if re.search(r'\b(?:AND|OR|NOT)\b', inner_str):
                    is_grouping = True
            
            stack.append((i, depth, is_grouping))
            if is_grouping:
                grouping_parens.add(i)
            depth += 1
            
        elif ch == ')':
            depth -= 1
            if stack:
                open_idx, open_depth, is_grouping = stack.pop()
                if is_grouping:
                    grouping_parens.add(i)
                    
                    # Also check what follows the closing paren
                    after = query[i+1:].lstrip()
                    if after:
                        next_tokens = after.split()
                        if next_tokens:
                            next_token = next_tokens[0].upper()
                            # If followed by operator, opening paren was definitely grouping
                            if next_token in OPERATORS or after.startswith(')'):
                                grouping_parens.add(open_idx)
                                grouping_parens.add(i)
        
        i += 1
    
    # Second pass: replace non-grouping parentheses with placeholders
    result = []
    for i, ch in enumerate(query):
        if ch == '(' and i not in grouping_parens:
            result.append('__LPAREN__')
        elif ch == ')' and i not in grouping_parens:
            result.append('__RPAREN__')
        else:
            result.append(ch)
    
    return ''.join(result)

class BooleanSearchFilter:
    """
    Utility to convert boolean search queries into SQLAlchemy filters.
    Supports boolean operators (AND, OR, NOT), wildcard '*', and array columns.
    Invalid queries return `false()` to avoid returning unintended data.
    """

    @classmethod
    def _parse_query(
        cls,
        query: str
    ) -> Optional[Union[str, Tuple[Expression, Dict[str, str]]]]:
        """
        Parses the boolean search query into an expression tree and
        a mapping of literals.

        args:
            query: The boolean search query string.
        returns:
            A tuple of (Expression, literals_map) or None if parsing fails.
        """
        if not re.search(r'\b(AND|OR|NOT)\b', query):
            return query.strip()

        query = sanitize_query(query)

        tokens = re.split(r'([()\s])', query)

        literals_map = {}
        symbol_counter = 0
        rebuilt_query_parts = []
        current_literal_parts = []

        OPERATORS = {'AND', 'OR', 'NOT'}
        VALID_PRECEDING_OPS = {'AND', 'OR', 'NOT', '('}

        def finalize_current_literal():
            nonlocal symbol_counter
            if not current_literal_parts:
                return

            literal_str = "".join(current_literal_parts).strip()
            if literal_str:
                # Restore any literal parentheses
                literal_str = (
                    literal_str
                    .replace('__LPAREN__', '(')
                    .replace('__RPAREN__', ')')
                )
                symbol_name = f"__LITERAL_{symbol_counter}__"
                literals_map[symbol_name] = literal_str
                rebuilt_query_parts.append(symbol_name)
                symbol_counter += 1
            current_literal_parts.clear()

        for part in tokens:
            stripped_part = part.strip()
            if stripped_part in OPERATORS or stripped_part in {'(', ')'}:
                finalize_current_literal()

                if stripped_part == 'NOT' and rebuilt_query_parts and rebuilt_query_parts[-1] not in VALID_PRECEDING_OPS:
                    rebuilt_query_parts.append('AND')

                rebuilt_query_parts.append(stripped_part)
            elif part:
                current_literal_parts.append(part)

        finalize_current_literal()

        if not rebuilt_query_parts:
            return None

        # Rebuild the query string
        clean_query = " ".join(rebuilt_query_parts)

        # Clean up dangling operators before parsing
        final_tokens = [token for token in clean_query.split() if token]
        if not final_tokens or final_tokens[-1] in OPERATORS:
            return None

        clean_query = " ".join(final_tokens)

        try:
            algebra = boolean.BooleanAlgebra()
            parsed_expr = algebra.parse(clean_query, simplify=True)
            return parsed_expr, literals_map
        except (ParseError, IndexError):
            return None
        except Exception:
            return None

    @classmethod
    def _build_filter_core(
        cls,
        parsed_result: Optional[Union[str, Tuple[Expression, Dict[str, str]]]],
        column: InstrumentedAttribute,
        array_mode: bool
    ) -> Union[BinaryExpression, BooleanClauseList, bool]:
        """
        Recursively builds the SQLAlchemy filter from the parsed result.
        It now respects user-defined wildcard placement.
        """
        if isinstance(parsed_result, str):
            if not parsed_result:
                return false()

            has_user_wildcard = '*' in parsed_result
            pattern = parsed_result.replace("*", "%")

            final_pattern = pattern

            # if has_user_wildcard:
            #     final_pattern = pattern
            # else:
            #     final_pattern = f"%{pattern}%"

            target = func.array_to_string(
                column,
                ","
            ) if array_mode else column
            return target.ilike(final_pattern)

        if isinstance(parsed_result, tuple):
            expr, literals_map = parsed_result

            if isinstance(expr, boolean.Symbol):
                term = literals_map.get(str(expr))
                if term is None:
                    return false()
                return cls._build_filter_core(term, column, array_mode)

            if isinstance(expr, boolean.NOT):
                inner_result = (expr.args[0], literals_map)
                return not_(
                    cls._build_filter_core(
                        inner_result,
                        column,
                        array_mode
                        )
                    )

            if isinstance(expr, boolean.AND):
                return and_(
                    *(
                        cls._build_filter_core(
                            (
                                arg,
                                literals_map
                            ),
                            column,
                            array_mode
                        )
                        for arg in expr.args
                    )
                )

            if isinstance(expr, boolean.OR):
                return or_(
                    *(
                        cls._build_filter_core(
                            (
                                arg,
                                literals_map
                            ),
                            column,
                            array_mode
                        )
                        for arg in expr.args
                    )
                )

        return false()

    @classmethod
    def _parse_and_build(
        cls,
        query: str,
        column: InstrumentedAttribute,
        array_mode: bool
    ) -> Union[BinaryExpression, BooleanClauseList, bool]:
        """
        Shared logic for parsing and building queries.
        """
        stripped_query = query.strip()
        if not stripped_query:
            return false()
        if stripped_query == "*":
            return true()

        is_boolean_query = bool(re.search(r'\b(AND|OR|NOT)\b', stripped_query))
        is_wildcard_query = '*' in stripped_query

        if not is_boolean_query and not is_wildcard_query:
            target = func.array_to_string(
                column,
                ","
            ) if array_mode else column

            return target.ilike(stripped_query)

        parsed_result = cls._parse_query(stripped_query)
        return cls._build_filter_core(parsed_result, column, array_mode)

    @classmethod
    def build_query(
        cls, query: str, column: InstrumentedAttribute
    ) -> Union[BinaryExpression, BooleanClauseList, bool]:
        """Build filter for a scalar column."""
        return cls._parse_and_build(query, column, array_mode=False)

    @classmethod
    def build_array_filter(
        cls, query: str, array_column: InstrumentedAttribute
    ) -> Union[BinaryExpression, BooleanClauseList, bool]:
        """Build filter for array columns (e.g., tag lists)."""
        return cls._parse_and_build(query, array_column, array_mode=True)
