"""
Vault utility functions
"""
import secrets
import string


def generate_password(length=16, use_uppercase=True, use_lowercase=True, use_digits=True, use_symbols=True):
    """
    Generate a secure random password.

    Args:
        length: Password length (default 16)
        use_uppercase: Include uppercase letters
        use_lowercase: Include lowercase letters
        use_digits: Include digits
        use_symbols: Include symbols

    Returns:
        str: Generated password
    """
    if length < 4:
        length = 4
    if length > 128:
        length = 128

    # Build character pool
    characters = ''
    required_chars = []

    if use_lowercase:
        characters += string.ascii_lowercase
        required_chars.append(secrets.choice(string.ascii_lowercase))

    if use_uppercase:
        characters += string.ascii_uppercase
        required_chars.append(secrets.choice(string.ascii_uppercase))

    if use_digits:
        characters += string.digits
        required_chars.append(secrets.choice(string.digits))

    if use_symbols:
        characters += '!@#$%^&*()_+-=[]{}|;:,.<>?'
        required_chars.append(secrets.choice('!@#$%^&*()_+-=[]{}|;:,.<>?'))

    if not characters:
        # Default to alphanumeric if nothing selected
        characters = string.ascii_letters + string.digits

    # Generate remaining characters
    remaining_length = length - len(required_chars)
    password_chars = required_chars + [secrets.choice(characters) for _ in range(remaining_length)]

    # Shuffle to avoid predictable patterns
    secrets.SystemRandom().shuffle(password_chars)

    return ''.join(password_chars)


def calculate_password_strength(password):
    """
    Calculate password strength score (0-100).

    Args:
        password: Password string to evaluate

    Returns:
        dict: {
            'score': int (0-100),
            'strength': str ('weak', 'fair', 'good', 'strong', 'excellent'),
            'feedback': list of str (improvement suggestions)
        }
    """
    if not password:
        return {'score': 0, 'strength': 'weak', 'feedback': ['Password is empty']}

    score = 0
    feedback = []

    # Length scoring
    length = len(password)
    if length >= 16:
        score += 30
    elif length >= 12:
        score += 20
    elif length >= 8:
        score += 10
    else:
        feedback.append('Password should be at least 12 characters long')

    # Character variety
    has_lowercase = any(c.islower() for c in password)
    has_uppercase = any(c.isupper() for c in password)
    has_digits = any(c.isdigit() for c in password)
    has_symbols = any(not c.isalnum() for c in password)

    variety_score = sum([has_lowercase, has_uppercase, has_digits, has_symbols]) * 10
    score += variety_score

    if not has_lowercase:
        feedback.append('Add lowercase letters')
    if not has_uppercase:
        feedback.append('Add uppercase letters')
    if not has_digits:
        feedback.append('Add numbers')
    if not has_symbols:
        feedback.append('Add special characters')

    # Bonus for longer passwords
    if length > 16:
        score += min(20, (length - 16) * 2)

    # Check for common patterns (penalty)
    common_patterns = ['123', 'abc', 'password', 'qwerty', '111', '000']
    password_lower = password.lower()
    for pattern in common_patterns:
        if pattern in password_lower:
            score -= 10
            feedback.append('Avoid common patterns and sequences')
            break

    # Cap score at 100
    score = min(100, max(0, score))

    # Determine strength label
    if score >= 80:
        strength = 'excellent'
    elif score >= 60:
        strength = 'strong'
    elif score >= 40:
        strength = 'good'
    elif score >= 20:
        strength = 'fair'
    else:
        strength = 'weak'

    return {
        'score': score,
        'strength': strength,
        'feedback': feedback if feedback else ['Password looks good!']
    }
