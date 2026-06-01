# LLM Provider Setup Guide

SIAgent uses [LiteLLM](https://docs.litellm.ai) as a unified interface to AI language models. Switching providers requires only two steps: set `LLM_MODEL` in your `.env` file, and provide the matching API key or credentials.

Everything else — the knowledge base, the UI, the ingestion pipeline — stays exactly the same.

---

## Choosing a provider

| Provider | Best for | Cost | Data leaves your network? |
|---|---|---|---|
| Anthropic Claude | Best answer quality, citation following | Paid per token | Yes — Anthropic servers |
| OpenAI | Widely supported, familiar to many teams | Paid per token | Yes — OpenAI servers |
| Azure OpenAI | Enterprise, data residency requirements | Paid per token | Yes — your Azure region |
| Ollama (local) | Air-gapped, sensitive data, zero ongoing cost | Free | No — stays on your machine |
| AWS Bedrock | AWS-native, enterprise compliance | Paid per token | Yes — your AWS region |

**Data residency:** if your documents contain sensitive or patient data, use Ollama (fully local) or Azure OpenAI / Bedrock in a region that meets your compliance requirements. Do not send sensitive content to a provider whose data processing terms you have not reviewed.

---

## Anthropic Claude (default)

**`.env` settings:**
```
LLM_MODEL=anthropic/claude-sonnet-4-6
ANTHROPIC_API_KEY=your-key-here
```

**Available models:**
| Model string | Speed | Quality | Cost |
|---|---|---|---|
| `anthropic/claude-haiku-4-5` | Fastest | Good | Lowest |
| `anthropic/claude-sonnet-4-6` | Balanced | Very good | Medium |
| `anthropic/claude-opus-4-7` | Slower | Best | Highest |

**Getting an API key:** sign up at [console.anthropic.com](https://console.anthropic.com), create an API key under **API Keys**.

---

## OpenAI

**`.env` settings:**
```
LLM_MODEL=openai/gpt-4o
OPENAI_API_KEY=your-key-here
```

**Available models:**
| Model string | Notes |
|---|---|
| `openai/gpt-4o` | Best quality |
| `openai/gpt-4o-mini` | Faster, lower cost |
| `openai/gpt-3.5-turbo` | Lowest cost |

**Getting an API key:** sign up at [platform.openai.com](https://platform.openai.com), go to **API keys**.

---

## Azure OpenAI

Use this when your organisation requires data to stay within a specific Azure region, or when procurement requires an enterprise agreement.

**`.env` settings:**
```
LLM_MODEL=azure/your-deployment-name
AZURE_API_KEY=your-key-here
AZURE_API_BASE=https://your-resource-name.openai.azure.com
AZURE_API_VERSION=2024-02-01
```

`your-deployment-name` is the name you gave the model when deploying it in Azure OpenAI Studio — not the model name itself.

**Setup steps:**
1. Create an Azure OpenAI resource in the [Azure portal](https://portal.azure.com)
2. Deploy a model in Azure OpenAI Studio (e.g. `gpt-4o`)
3. Copy the endpoint URL, API key, and deployment name into your `.env`

---

## Ollama — fully local, no API key

Ollama runs open-weight models entirely on your own machine or server. No data leaves your network, no ongoing cost, no API key needed. Suitable for sensitive data environments.

**`.env` settings:**
```
LLM_MODEL=ollama/llama3
# No API key needed
```

**Setup steps:**

1. Install Ollama from [ollama.com](https://ollama.com)

2. Pull a model (run this once in your terminal):
```cmd
ollama pull llama3
```

3. Ollama starts a local server automatically. Leave it running while using SIAgent.

**Recommended models for this use case:**
| Model string | Size | Notes |
|---|---|---|
| `ollama/llama3` | ~4GB | Good general quality |
| `ollama/llama3:70b` | ~40GB | Better quality, needs a powerful machine |
| `ollama/mistral` | ~4GB | Fast, good for structured answers |
| `ollama/phi3` | ~2GB | Lightweight, works on modest hardware |

**Hardware requirements:** at minimum, 8GB RAM for smaller models. 16GB+ recommended for comfortable performance. A GPU will significantly speed up responses but is not required.

---

## AWS Bedrock

Use this when running on AWS infrastructure and you want to keep AI API calls within your AWS account.

**`.env` settings:**
```
LLM_MODEL=bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0
AWS_REGION=us-east-1
# No separate API key — uses your AWS credentials
```

**Authentication:** Bedrock uses your existing AWS credentials. In order of preference:
1. IAM role attached to your EC2 / ECS task (recommended for production)
2. `~/.aws/credentials` file (for local development)
3. `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` environment variables

**Setup steps:**
1. Enable model access in the [AWS Bedrock console](https://console.aws.amazon.com/bedrock/) under **Model access**
2. Ensure your IAM role or user has `bedrock:InvokeModel` permission
3. Set `AWS_REGION` to the region where you enabled the model

**Available models on Bedrock:**
| Model string | Notes |
|---|---|
| `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0` | Claude on AWS |
| `bedrock/amazon.titan-text-express-v1` | Amazon's own model |
| `bedrock/meta.llama3-8b-instruct-v1:0` | Llama 3 on AWS |

---

## Troubleshooting

| Error | Likely cause | Fix |
|---|---|---|
| `AuthenticationError` | Wrong or missing API key | Check the key in `.env` matches the provider |
| `Model not found` | Incorrect model string | Check the model string exactly — including the prefix (e.g. `anthropic/`) |
| `Connection refused` (Ollama) | Ollama server not running | Run `ollama serve` in a separate terminal |
| `ResourceNotFound` (Azure) | Wrong deployment name | Use the deployment name, not the model name |
| `AccessDeniedException` (Bedrock) | Model not enabled or missing IAM permission | Enable the model in Bedrock console, check IAM policy |

---

## Adding a provider not listed here

LiteLLM supports 100+ providers including Cohere, Mistral, Groq, Hugging Face, and more. Full list at [docs.litellm.ai/docs/providers](https://docs.litellm.ai/docs/providers).

The pattern is always the same:
1. Set `LLM_MODEL=provider/model-name` in `.env`
2. Set the provider's API key environment variable
3. No code changes needed
