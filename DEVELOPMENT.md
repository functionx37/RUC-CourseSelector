# 人大教务系统接口参考

本接口文档仅由作者测试得出，不代表官方接口文档，不保证长期有效。

## 会话与鉴权

- 起始页：`https://jw.ruc.edu.cn/Njw2017/index.html#/`
- 登录后业务接口前缀：

  ```text
  https://jw.ruc.edu.cn/resService/jwxtpt/v1/xsd/stuCourseCenterController/
  ```

- 已观察到的请求头：

  ```text
  Cookie: <当前浏览器会话>
  TOKEN: <当前会话令牌>
  userRoleCode: student
  app: PCWEB
  locale: zh_CN
  X-Requested-With: XMLHttpRequest
  Content-Type: application/json
  Origin: <浏览器实际值>
  Referer: <浏览器实际值>
  User-Agent: <浏览器实际值>
  ```

- URL 查询参数 `resourceCode`、`apiCode` 和所有浏览器头应原样复用。
- `Host`、`Connection`、`Content-Length` 由 HTTP 客户端生成；重放时使用 `Accept-Encoding: identity`。

## 已观察接口

|用途|方法|
|---|---|
|选课阶段列表|`findXsxkjdList`|
|读取单个选课阶段|`findXsxkjdByOne`|
|按入口读取选课信息|`findZxxkByEntry`|
|读取选课资源|`findXkResList`|
|按分类读取课程列表|`findKcInfoByflByRmdx`|
|加载课程/教学班详情|`findZxKcByXxkc`|
|读取当前用户课表|`getUserKb`|
|选课前校验|`getStuXkByRmdxCq`|
|提交选课|`saveStuXkByRmdx`|
|退选课程|`saveStuTxByRmdx`|

所有已观察接口均为 JSON `POST`。

## 教学班标识与完整课程对象

`saveStuXkByRmdx` 接收完整课程对象，关键字段如下：

```text
id / kkgl004id       教学班内部标识
kth                  页面展示的教学班号
jczy013id            学期
xkgl017id            选课入口
xkgl019id            选课阶段
kcbh / kcmc_name     课程编号和名称
ktmc_name            教学班名称
kclb / kclbMapper    课程类别
xklbbh               选课类别
skls_name            教师及相关上下文
sksj                 上课时间
zydata / bllsZyId    培养方案或选课上下文
```

课程列表记录可能同时含 `id`、`kkgl004id`、`kth`。匹配时依次兼容三者。

## 余量查询

### 接口与请求体

```text
POST findKcInfoByflByRmdx
```

浏览器请求体包含：

```text
jczy013id
xkfl                         空数组
xklbbh
xkgl017id
xkgl019id
bllsZyId
kclbCodeMapper               当前课程分类
page.pageIndex               0
page.pageSize                0
page.conditions              页面生成的不透明筛选条件
```

`bllsZyId`、`page.conditions`、`kclbCodeMapper`、入口和阶段 ID 都是当前会话上下文。
提交体中的 `kclbMapper` 对应列表请求中的 `kclbCodeMapper`。

### 响应与字段

成功响应：

```json
{
  "errorCode": "success",
  "errorMessage": "success",
  "data": {
    "showKclist": []
  }
}
```

目标教学班位于 `data.showKclist[]`：

```text
xkrs    已选人数
xxrs    最大人数
```

`findZxKcByXxkc` 可返回 `data.returnMsg`，但当前未发现可替代 `xkrs/xxrs` 的余量字段。

## 选课前校验

```text
POST getStuXkByRmdxCq
```

已观察到的请求字段：

```text
xkgl019id
xklbbh
kclbMapper
kkgl004id
jczy013id
isSxrz
```

响应可包含 `xkcscode12`、`allIsAbled` 和志愿/培养方案结构。`allIsAbled: false` 不能单独作为拒绝提交的条件。

## 选课提交

```text
POST saveStuXkByRmdx
```

请求使用：

1. 当前浏览器请求中的完整 URL 和请求头；
2. 用户手动点击选课时采集的完整课程对象作为 JSON 请求体。


### 响应

所有已观察到的业务响应均可能返回 HTTP 200；必须使用 `errorCode` 和 `errorMessage` 判断。

|`errorCode` / `errorMessage`|含义|
|---|---|
|`success`|服务端接受选课申请|
|`eywxt.save.cantXkByCopy.error`|课程已选|
|`请选择其他志愿`|选课志愿冲突|

成功响应形态：

```json
{
  "errorCode": "success",
  "errorMessage": "success",
  "errorMessageParam": [],
  "data": null
}
```

失败响应同样可能是 HTTP 200，且 `data`、`errorMessageParam` 可能为 `null`。
