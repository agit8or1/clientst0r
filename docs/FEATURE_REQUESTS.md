# 💡 Feature Requests & Voting

HuduGlue uses a community-driven approach to feature development. This guide explains how to suggest features, vote on ideas, and track what's being worked on.

---

## Table of Contents

- [Quick Start](#quick-start)
- [The Process](#the-process)
- [How to Suggest a Feature](#how-to-suggest-a-feature)
- [How to Vote](#how-to-vote)
- [Tracking the Roadmap](#tracking-the-roadmap)
- [Feature Request Lifecycle](#feature-request-lifecycle)
- [FAQ](#faq)

---

## Quick Start

**Want to suggest a new feature?**

1. **Start with a Discussion** → [Share your idea here](https://github.com/agit8or1/huduglue/discussions/new?category=ideas)
2. **Vote on existing ideas** → [Browse and upvote](https://github.com/agit8or1/huduglue/discussions/categories/ideas) (👍 reaction)
3. **Track progress** → [View the Roadmap](https://github.com/agit8or1/huduglue/projects)

**Already have a detailed specification?**

→ [Create a Feature Request Issue](https://github.com/agit8or1/huduglue/issues/new?template=feature_request.yml)

---

## The Process

HuduGlue uses a **two-stage system** for feature development:

### Stage 1: Ideas & Discussion 💬

- **Where:** [GitHub Discussions → Ideas](https://github.com/agit8or1/huduglue/discussions/categories/ideas)
- **Purpose:** Explore, refine, and gather community feedback
- **Who:** Anyone can post and vote (👍 reactions)
- **Timeline:** Open-ended discussion

### Stage 2: Structured Request 📋

- **Where:** [GitHub Issues → Feature Request](https://github.com/agit8or1/huduglue/issues/new?template=feature_request.yml)
- **Purpose:** Formal specification ready for implementation
- **Who:** Maintainers promote from discussions, or users can submit directly
- **Timeline:** Tracked on the [Roadmap Project](https://github.com/agit8or1/huduglue/projects)

---

## How to Suggest a Feature

### Option A: Start with a Discussion (Recommended)

**Use this if:**
- You're exploring an idea and want feedback
- You're not sure if it fits HuduGlue's scope
- You want to gauge community interest first

**Steps:**
1. Go to [Discussions → Ideas](https://github.com/agit8or1/huduglue/discussions/new?category=ideas)
2. Use the "Idea" template
3. Fill in:
   - **The Idea:** What should HuduGlue do?
   - **Problem:** What pain point does this solve?
   - **Benefit:** Who would use this?
4. Submit and share with the community!

**What happens next:**
- Community members discuss and upvote (👍 on the first post)
- Maintainers review popular ideas weekly
- High-voted ideas are promoted to Feature Request issues

---

### Option B: Submit a Feature Request Directly

**Use this if:**
- You have a well-defined specification
- Your idea came from an approved Discussion
- You're ready to contribute to implementation

**Steps:**
1. Go to [Issues → New Feature Request](https://github.com/agit8or1/huduglue/issues/new?template=feature_request.yml)
2. Fill in the structured form:
   - **Problem Statement:** The pain point you're solving
   - **Proposed Solution:** How it should work
   - **Priority:** Impact on your workflow
   - **Feature Area:** Which part of HuduGlue (Assets, Vault, etc.)
   - **Use Case:** Real-world scenario
3. Submit for triage

**Triage process:**
- Maintainers label and prioritize within 1 week
- Status changes: `needs-triage` → `status:planned` → `status:in-progress` → `status:completed`
- You'll be notified at each stage

---

## How to Vote

Voting helps prioritize features based on community need.

### Voting on Discussions (Ideas)

1. Browse [Ideas Category](https://github.com/agit8or1/huduglue/discussions/categories/ideas)
2. Read the idea thoroughly
3. **👍 Upvote** the first post if you want this feature
4. ❌ Avoid "+1" comments—use reactions instead
5. 💬 Add constructive feedback in the replies

**Vote weight:**
- 1-5 votes: Low priority
- 6-15 votes: Medium priority
- 16-30 votes: High priority
- 31+ votes: Very high priority

### Voting on Issues (Feature Requests)

Once an idea becomes a Feature Request issue:
1. **👍 Upvote** the issue
2. **Subscribe** to receive updates
3. **Contribute** if you have technical skills

---

## Tracking the Roadmap

The [Roadmap Project Board](https://github.com/agit8or1/huduglue/projects) shows what's being worked on.

### Project Columns

| Column | Description |
|--------|-------------|
| **💡 Triage** | New requests being evaluated |
| **📋 Planned** | Approved for development (prioritized backlog) |
| **🚧 In Progress** | Actively being worked on |
| **✅ Done** | Completed and released |
| **🧊 On Hold** | Deferred pending dependencies |
| **❌ Won't Do** | Declined with explanation |

### Status Labels

Issues are labeled with:
- `status:triage` → Being evaluated
- `status:planned` → Approved, in backlog
- `status:in-progress` → Active development
- `status:completed` → Shipped in a release
- `status:blocked` → Waiting on external factors
- `status:wontfix` → Declined (see issue for reason)

---

## Feature Request Lifecycle

```
1. [Idea Discussion] 💡
   ↓
   (Community upvotes & discusses)
   ↓
2. [Triage Review] 📊
   ↓
   (Maintainer evaluates feasibility + priority)
   ↓
3. [Feature Request Issue] 📋
   ↓
   (Added to Roadmap Project → Planned column)
   ↓
4. [Development] 🔨
   ↓
   (Moved to In Progress → assigned to milestone)
   ↓
5. [Testing & Review] 🧪
   ↓
   (Pull request reviewed)
   ↓
6. [Release] 🚀
   ↓
   (Merged, documented in CHANGELOG)
   ↓
7. [Done] ✅
   (Closed, moved to Done column)
```

**Timeline expectations:**
- **Triage:** 3-7 days
- **Small features:** 1-4 weeks
- **Medium features:** 1-2 months
- **Large features:** 3-6 months
- **Complex features:** 6+ months (multi-release)

---

## FAQ

### Q: How long until my feature is implemented?

**A:** It depends on:
- **Priority:** Critical bugs > high-priority features > nice-to-haves
- **Complexity:** Simple UI changes are faster than new integrations
- **Community votes:** High-voted features move up the queue
- **Contributor availability:** Open-source maintainers work on a best-effort basis

You can speed things up by:
- Contributing code yourself (see [CONTRIBUTING.md](CONTRIBUTING.md))
- Funding development (contact maintainers for sponsorship)
- Helping with testing and documentation

---

### Q: Can I sponsor a specific feature?

**A:** Yes! If you need a feature urgently:
1. Comment on the Discussion/Issue expressing interest
2. Reach out to maintainers via [GitHub Sponsors](https://github.com/sponsors/agit8or1) or create a "Sponsorship Request" discussion
3. Negotiate scope and timeline

---

### Q: My idea was closed as "Won't Do"—why?

**A:** Common reasons:
- **Out of scope:** Doesn't align with HuduGlue's core purpose (IT documentation platform)
- **Security risk:** Would introduce vulnerabilities
- **Maintenance burden:** Would create long-term technical debt
- **Better alternatives:** Existing features or integrations solve the problem
- **Edge case:** Benefits too few users to justify complexity

If you disagree, you can:
- Request clarification in the issue comments
- Propose a modified version that addresses concerns
- Implement it as a third-party plugin/extension

---

### Q: Can I work on a feature that's "Planned" but not "In Progress"?

**A:** Absolutely! Before starting:
1. Comment on the issue saying you want to work on it
2. Wait for maintainer approval to avoid wasted effort
3. Read [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines
4. Open a draft PR early to get feedback

---

### Q: I found a bug—should I use this process?

**A:** **No.** Bugs should be reported via the [Bug Report template](https://github.com/agit8or1/huduglue/issues/new?template=bug_report.yml), not as feature requests.

Bug fixes are prioritized separately and don't go through voting.

---

### Q: Can I suggest multiple features in one Discussion/Issue?

**A:** **No.** Please create separate submissions for each feature so they can be:
- Voted on independently
- Tracked individually
- Implemented in different releases

Exception: If features are tightly coupled (e.g., "Add Markdown support" and "Add Markdown preview"), mention both but focus on the primary feature.

---

### Q: How do I know if a feature is already being discussed?

**Before posting:**
1. Search [Discussions → Ideas](https://github.com/agit8or1/huduglue/discussions?discussions_q=category%3AIdeas)
2. Search [Issues with `type:feature` label](https://github.com/agit8or1/huduglue/issues?q=is%3Aissue+label%3Atype%3Afeature)
3. Check the [Roadmap Project](https://github.com/agit8or1/huduglue/projects)

If you find a duplicate:
- Upvote it instead of creating a new one
- Add your unique use case in a comment

---

### Q: Can I create polls for feature voting?

**A:** Yes! Use [GitHub Discussions Polls](https://github.com/agit8or1/huduglue/discussions/new?category=polls) to:
- Vote on UI design options
- Prioritize multiple related features
- Gather feedback on breaking changes

Maintainers may also create periodic "What should we build next?" polls.

---

## Getting Help

**Need clarification on the process?**
- 💬 [Discussions → Q&A](https://github.com/agit8or1/huduglue/discussions/categories/q-a)
- 📧 Email: [your-support-email]
- 💻 Join our [Discord/Slack community] (if applicable)

**Want to contribute code?**
- 📖 Read [CONTRIBUTING.md](CONTRIBUTING.md)
- 🛠️ Check [Good First Issues](https://github.com/agit8or1/huduglue/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)

---

## Summary: When to Use What

| Scenario | Use This | Link |
|----------|----------|------|
| Exploring a new idea | 💬 Discussion (Idea) | [Start here](https://github.com/agit8or1/huduglue/discussions/new?category=ideas) |
| Voting on existing ideas | 👍 Upvote discussions | [Browse Ideas](https://github.com/agit8or1/huduglue/discussions/categories/ideas) |
| Proposing a feature with full spec | 📋 Feature Request Issue | [Create Issue](https://github.com/agit8or1/huduglue/issues/new?template=feature_request.yml) |
| Tracking what's being built | 🗺️ Roadmap Project | [View Roadmap](https://github.com/agit8or1/huduglue/projects) |
| Reporting a bug | 🐛 Bug Report | [Report Bug](https://github.com/agit8or1/huduglue/issues/new?template=bug_report.yml) |
| Asking a question | ❓ Q&A Discussion | [Ask here](https://github.com/agit8or1/huduglue/discussions/new?category=q-a) |

---

**Thank you for helping shape the future of HuduGlue!** 🚀
