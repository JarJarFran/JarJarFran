### Hi there 👋

# 💫 About Me:
Data engineer working on LLM inference for Apple silicon.
<br>By day I build streaming and batch data pipelines (Kafka, Spark, SQL, AWS). On my own time I build
[**Espetero**](https://github.com/JarJarFran/espetero), a native C++20/Metal LLM engine for Apple silicon, and send what
I learn there upstream to the Mac inference projects.

## 🚀 Espetero
[Espetero](https://github.com/JarJarFran/espetero): fast LLM inference for Apple silicon. It is a native Metal engine
with OpenAI, Anthropic and Ollama APIs, MLX and GGUF weights, MTP speculative decoding, continuous batching and vision.
Install it with `brew install JarJarFran/espetero/espetero`.

## 🤝 Open-source contributions
**Merged**
- [vllm-project/vllm-metal#1193](https://github.com/vllm-project/vllm-metal/pull/1193): serve images on MLX-quantized Qwen3.5/3.6 MoE checkpoints
- [jundot/omlx#4712](https://github.com/jundot/omlx/pull/4712): keep system notes after a tool result out of the leading system block
- [antranapp/awesome-mlx#55](https://github.com/antranapp/awesome-mlx/pull/55): add Espetero

**In review**
- [jundot/omlx#4842](https://github.com/jundot/omlx/pull/4842): MoE offload releases only the expert slots a prefill needs
- [jundot/omlx#4762](https://github.com/jundot/omlx/pull/4762): snapshot and protect the system prefix of hybrid models in the cache
- [jundot/omlx#4891](https://github.com/jundot/omlx/pull/4891): enforce `required` and named `tool_choice` on chat completions
- [Blaizzy/mlx-vlm#2597](https://github.com/Blaizzy/mlx-vlm/pull/2597): keep MTP speculative decoding for `response_format` requests
- [Blaizzy/mlx-vlm#2595](https://github.com/Blaizzy/mlx-vlm/pull/2595): add the Kev decision models
- [Blaizzy/mlx-vlm#2564](https://github.com/Blaizzy/mlx-vlm/pull/2564): share storage between fused GDN decode projections and their sources

**Benchmarks and reports for maintainers**
- [vllm-project/vllm-metal#1185](https://github.com/vllm-project/vllm-metal/pull/1185) and [#1159](https://github.com/vllm-project/vllm-metal/pull/1159) (both merged): M1 Max serving and decode-split measurements, with Metal System Traces
- [vllm-project/vllm-metal#695](https://github.com/vllm-project/vllm-metal/issues/695): TurboQuant A/B on M1 Max
- [ashhart/TensorFold#918](https://github.com/ashhart/TensorFold/issues/918): M1 Max prefill profile that traced the slowdown to the pre-M5 attention tail kernel

## 🌐 Socials:
[![LinkedIn](https://img.shields.io/badge/LinkedIn-%230077B5.svg?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/francisco-jose-garcia-barbero)

# 💻 Tech Stack:
![Python](https://img.shields.io/badge/python-3670A0?style=flat&logo=python&logoColor=ffdd54) ![C++](https://img.shields.io/badge/c++-%2300599C.svg?style=flat&logo=c%2B%2B&logoColor=white) ![Metal](https://img.shields.io/badge/Metal-000000?style=flat&logo=apple&logoColor=white) ![MLX](https://img.shields.io/badge/MLX-000000?style=flat&logo=apple&logoColor=white) ![Scala](https://img.shields.io/badge/scala-%23DC322F.svg?style=flat&logo=scala&logoColor=white) ![Apache Spark](https://img.shields.io/badge/Apache%20Spark-FDEE21?style=flat&logo=apachespark&logoColor=black) ![Apache Kafka](https://img.shields.io/badge/Apache%20Kafka-000?style=flat&logo=apachekafka) ![Apache Airflow](https://img.shields.io/badge/Apache%20Airflow-017CEE?style=flat&logo=Apache%20Airflow&logoColor=white) ![AWS](https://img.shields.io/badge/AWS-%23FF9900.svg?style=flat&logo=amazon-aws&logoColor=white) ![Terraform](https://img.shields.io/badge/terraform-%235835CC.svg?style=flat&logo=terraform&logoColor=white) ![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=flat&logo=docker&logoColor=white) ![Pandas](https://img.shields.io/badge/pandas-%23150458.svg?style=flat&logo=pandas&logoColor=white)
# 📊 GitHub Stats:
![](https://github-readme-stats.vercel.app/api?username=JarJarFran&theme=dark&hide_border=false&include_all_commits=true&count_private=true)<br/>
![](https://github-readme-streak-stats.herokuapp.com/?user=JarJarFran&theme=dark&hide_border=false)<br/>
![](https://github-readme-stats.vercel.app/api/top-langs/?username=JarJarFran&theme=dark&hide_border=false&include_all_commits=true&count_private=true&layout=compact)
