# 各评测登记时的模型（A1c、A2 都登记为 deepseek-flash）；换模型是登记变更。
# 评测程序逐个角色检查 provider.model_for(role) 与这里一致，才允许开跑。
REGISTERED_MODELS = {"loop": "deepseek-flash", "route": "deepseek-flash", "requests": "deepseek-flash"}
