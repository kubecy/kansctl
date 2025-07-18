<!-- Logo -->
<img src="https://github.com/kubecy/kansctl/blob/main/pics/kansctl-logo.png?raw=true" width="220px" alt="kansctl logo"/>

<!-- Badges -->
<a href="#"><img src="https://img.shields.io/badge/Platform-Kubernetes-informational?logo=kubernetes&logoColor=white&color=326ce5" /></a>
<a href="#"><img src="https://img.shields.io/badge/Framework-Ansible-red?logo=ansible&logoColor=white" /></a>
<a href="#"><img src="https://img.shields.io/badge/Environment-Multi--env-yellow?logo=gnu&color=yellow" /></a>
<a href="#"><img src="https://img.shields.io/badge/Shell-Bash-green?logo=gnubash&logoColor=white" /></a>

---

# kansctl 是什么
**`kansctl`** 是一款基于 **`Shell + Ansible`** 构建的中间件自动化部署与交付工具，专为 Kubernetes 场景设计。该工具旨在简化 **中间件环境交付** 及 **多环境多服务部署流程**，具备如下特点：
<table> <thead> <tr> <th align="left" width="200px">🌟 功能</th> <th align="left">✨ 描述</th> </tr> </thead> <tbody>
<tr> <td>🧩 服务粒度控制</td> <td> 按服务维度精细控制中间件部署与卸载，例如支持独立部署 Redis、MySQL、Elasticsearch、Prometheus 等组件。</td> </tr>
<tr> <td>🏗️ 多环境支持</td> <td> 支持按环境变量组织部署逻辑（如 <code>dev</code>、<code>test</code>、<code>prod</code>），可加载对应配置文件，灵活适配多套部署体系，提升交付效率。</td> </tr>
<tr> <td>⚙️ 自动化引擎</td> <td> 基于 Ansible 实现声明式部署逻辑，确保中间件部署过程的标准化、一致性与可重复性，适合 CI/CD 和持续交付场景。</td> </tr> 
<tr> <td>💣 安全清理机制</td> <td> 所有删除服务操作前将触发 <strong>倒计时确认机制</strong>，可手动中断操作，有效避免误删行为。</td> </tr> 
<tr> <td>📜 日志记录</td> <td> 全流程日志实时输出，并同步写入日志文件，便于问题回溯、部署审计以及历史操作追踪。 </td> </tr> 
<tr> <td>🔄 一键全量部署/卸载</td> <td> 一键部署或卸载所有中间件服务，适用于 **PoC**  快速部署、测试环境批量初始化等场景。 </td> </tr>
<tr> <td>✨ 可扩展性强</td> <td> 所有服务基于 <code>roles</code> 模块化设计，用户可按需添加新中间件支持（如 Kafka、Zookeeper、Nacos），快速扩展业务能力。 </td> </tr> </tbody> </table>

# 安装
```
root@kubecy-master21 /root:~ # dnf -y install git ansible
root@kubecy-master21 /root:~ # mkdir .kubecy
root@kubecy-master21 /root:~ # cd .kubecy/
root@kubecy-master21 /root/.kubecy:~ # git clone https://github.com/kubecy/kansctl.git
root@kubecy-master21 /root/.kubecy:~ # cd kansctl/
```

# 使用
### 部署单个服务
```
root@kubecy-master21 /root/.kubecy/kansctl:~ # ./kansctl apply -e moone_prod -t  prometheus
```

### 部署多个服务
```
root@kubecy-master21 /root/.kubecy/kansctl:~ # ./kansctl apply -e moone_prod -t  redis-single,postgresql-single
```

### 部署全部服务

```
root@kubecy-master21 /root/.kubecy/kansctl:~ # ./kansctl apply -e moone_prod -t  all
```
---


