# Contributing to HuduGlue

First off, thank you for considering contributing to HuduGlue! 🐕

This document provides guidelines for contributing to the project. Luna the GSD has helped review these guidelines to ensure they're clear and effective.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)

## 🤝 Code of Conduct

This project adheres to a Code of Conduct. By participating, you are expected to uphold this code. Please report unacceptable behavior to conduct@yourdomain.com.

## 🎯 How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues. When creating a bug report, include:

- **Clear title and description**
- **Steps to reproduce**
- **Expected vs actual behavior**
- **Environment details** (OS, Python version, database version)
- **Screenshots** (if applicable)
- **Error logs** (with sensitive data removed)

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion, include:

- **Clear title and description**
- **Use case** - Why is this enhancement needed?
- **Proposed solution**
- **Alternative solutions** considered
- **Additional context** or screenshots

### Your First Code Contribution

Unsure where to begin? Look for issues labeled:
- `good first issue` - Simple issues for beginners
- `help wanted` - Issues where we need community help
- `documentation` - Documentation improvements

### Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Write or update tests
5. Update documentation
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## 🛠️ Development Setup

### Prerequisites

- Python 3.12+
- MariaDB 10.5+ or MySQL 8.0+
- Git
- Virtual environment tool

### Setup Steps

```bash
# 1. Fork and clone
git clone https://github.com/yourusername/huduglue.git
cd huduglue

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Development dependencies

# 4. Set up environment
cp .env.example .env
# Edit .env with your local settings

# 5. Create database
mysql -u root -p
CREATE DATABASE huduglue_dev CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'huduglue_dev'@'localhost' IDENTIFIED BY 'dev_password';
GRANT ALL PRIVILEGES ON huduglue_dev.* TO 'huduglue_dev'@'localhost';
FLUSH PRIVILEGES;
EXIT;

# 6. Run migrations
python3 manage.py migrate

# 7. Create superuser
python3 manage.py createsuperuser

# 8. Run development server
python3 manage.py runserver
```

### Development Tools

We recommend:
- **IDE**: VS Code, PyCharm, or your preferred editor
- **Database Client**: DBeaver, MySQL Workbench, or similar
- **API Testing**: Postman, Insomnia, or curl
- **Browser DevTools**: Chrome/Firefox Developer Tools

## 📝 Pull Request Process

### Before Submitting

1. **Ensure tests pass**: `python3 manage.py test`
2. **Check code style**: Follow PEP 8
3. **Update documentation**: Document new features
4. **Update CHANGELOG**: Add entry for your changes
5. **Rebase on main**: Ensure your branch is up to date

### PR Checklist

- [ ] Code follows project style guidelines
- [ ] Tests written and passing
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] No merge conflicts
- [ ] Commit messages are clear
- [ ] Security considerations addressed

### PR Description Template

```markdown
## Description
Brief description of what this PR does

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## Testing
Describe the tests you ran and how to reproduce them

## Screenshots
If applicable, add screenshots

## Checklist
- [ ] Tests pass locally
- [ ] Documentation updated
- [ ] CHANGELOG updated
- [ ] No security issues introduced
```

## 🎨 Coding Standards

### Python Style Guide

Follow **PEP 8** with these specifics:

```python
# Good
def calculate_total_cost(items, tax_rate=0.0):
    """Calculate total cost including tax."""
    subtotal = sum(item.price for item in items)
    return subtotal * (1 + tax_rate)

# Bad
def calc_cost(i,t=0):
    s=sum([x.price for x in i])
    return s*(1+t)
```

### Django Best Practices

- Use Django ORM instead of raw SQL when possible
- Always use parameterized queries
- Follow Django's model conventions
- Use Django's built-in authentication and permissions
- Validate all user input
- Escape output to prevent XSS

### Security Practices

- **Never commit secrets** - Use environment variables
- **Validate input** - Never trust user input
- **Parameterize queries** - Prevent SQL injection
- **Escape output** - Prevent XSS
- **Check permissions** - Verify user authorization
- **Log security events** - Use audit logging
- **Encrypt sensitive data** - Use provided encryption utilities

### Code Organization

```
huduglue/
├── apps/              # Django apps
│   ├── core/         # Core functionality
│   ├── vault/        # Password vault
│   ├── assets/       # Asset management
│   └── ...
├── config/           # Django settings
├── templates/        # HTML templates
├── static/           # CSS, JS, images
├── docs/             # Documentation
└── scripts/          # Utility scripts
```

## 🧪 Testing

### Running Tests

```bash
# Run all tests
python3 manage.py test

# Run specific app tests
python3 manage.py test core

# Run specific test
python3 manage.py test core.tests.test_models.OrganizationTestCase

# Run with coverage
coverage run --source='.' manage.py test
coverage report
coverage html  # Generate HTML report
```

### Writing Tests

```python
from django.test import TestCase
from core.models import Organization

class OrganizationTestCase(TestCase):
    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )

    def test_organization_creation(self):
        """Test organization is created correctly."""
        self.assertEqual(self.org.name, "Test Org")
        self.assertEqual(self.org.slug, "test-org")

    def test_organization_str(self):
        """Test string representation."""
        self.assertEqual(str(self.org), "Test Org")
```

### Test Coverage Goals

- **Minimum**: 70% coverage
- **Target**: 85% coverage
- **Critical paths**: 100% coverage (authentication, encryption, payments)

## 📚 Documentation

### Code Documentation

```python
def encrypt_password(plaintext: str, master_key: bytes) -> str:
    """
    Encrypt a password using AES-GCM.

    Args:
        plaintext: The plaintext password to encrypt
        master_key: The master encryption key (32 bytes)

    Returns:
        Base64-encoded string containing nonce + ciphertext

    Raises:
        ValueError: If master_key is invalid
        EncryptionError: If encryption fails

    Example:
        >>> encrypted = encrypt_password("mypassword", master_key)
        >>> decrypted = decrypt_password(encrypted, master_key)
        >>> assert decrypted == "mypassword"
    """
    # Implementation here
```

### User Documentation

- Update relevant docs in `docs/` directory
- Include screenshots for UI changes
- Provide examples for new features
- Update API documentation for API changes

### Commit Messages

Follow conventional commits:

```
type(scope): brief description

Longer description if needed

Fixes #123
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style changes
- `refactor`: Code refactoring
- `test`: Adding/updating tests
- `chore`: Maintenance tasks

Examples:
```
feat(vault): add password generator with strength meter

Implements secure password generation with configurable options:
- Length (8-128 characters)
- Character types (uppercase, lowercase, digits, symbols)
- Real-time strength calculation
- Have I Been Pwned integration

Fixes #42
```

## 🔍 Code Review Process

### What We Look For

- **Functionality**: Does it work as intended?
- **Code Quality**: Is it readable and maintainable?
- **Tests**: Are there adequate tests?
- **Security**: Are there security implications?
- **Performance**: Is it efficient?
- **Documentation**: Is it documented?

### Review Timeline

- **Initial Review**: Within 3 business days
- **Follow-up**: Within 2 business days after changes
- **Merge**: After 1 approval from maintainer

## 🏷️ Issue and PR Labels

- `bug` - Something isn't working
- `enhancement` - New feature or request
- `documentation` - Documentation improvements
- `good first issue` - Good for newcomers
- `help wanted` - Extra attention needed
- `security` - Security-related issue
- `wontfix` - Will not be worked on
- `duplicate` - Duplicate issue/PR
- `invalid` - Invalid issue/PR

## 🎁 Recognition

Contributors are recognized in:
- CHANGELOG.md for their contributions
- GitHub contributor graph
- Project README (for significant contributions)

## 🐾 Luna's Development Tips

1. **Write tests first** - TDD helps catch issues early
2. **Keep PRs focused** - One feature or fix per PR
3. **Document as you go** - Future you will thank present you
4. **Ask questions** - No question is too small
5. **Review others' code** - Learn from the community
6. **Be patient** - Quality reviews take time
7. **Celebrate successes** - You're contributing to open source! 🎉

## 📞 Getting Help

- **GitHub Issues**: For bugs and features
- **GitHub Discussions**: For questions and ideas
- **Email**: dev@yourdomain.com for private inquiries

## 📄 License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

**Thank you for contributing to HuduGlue! 🐕**

*Reviewed by Luna the German Shepherd*
