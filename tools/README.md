# 批量整理曲库

不调用AI，不逐首打开网页。流程为：离线读取资料 → 低频获取公开投稿 → 生成待核对清单 → 明确确认后导出。不会自动发布，也不会改服务器正在使用的曲库。

## 准备

使用 Python 3.10+。内置1,039首歌的压缩资料索引，默认无需访问百科网站或额外安装依赖。只包含歌曲元数据，不含歌词。要更新索引时，才需要本地神椿观测站仓库和本目录requirements.txt中的PyYAML。资料来源：https://github.com/LinkTh1rsty/kamitsubaki-wiki-site 。

在本插件仓库根目录执行：

```sh
python tools/build_catalog.py wiki
python tools/build_catalog.py collect --max-requests 10
python tools/build_catalog.py match
```

`channels.json` 目前只填入资料明确链接的花譜、春猿火、ヰ世界情緒三个B站账号，附证据页面。其他歌手待核对账号后再添加，不能根据名字猜账号。脚本的歌手范围可以包含其他神椿歌手；实际新增数量取决于可取得的投稿和匹配结果。

## 网络限制

- 投稿列表已改为 `/x/space/wbi/arc/search`，使用 nav 返回的公开公钥计算 WBI 签名；不需要提供密码或 Cookie。取公钥也计入请求上限。首次验证至少需要2次请求预算（公钥1次、投稿列表1次）。这是接口兼容修正，不保证消除服务器IP或设备校验限制；收到拒绝仍立即暂停，不尝试其他接口或伪造设备参数。

- 单进程串行请求，相邻请求至少8秒；单次默认最多10次，硬上限50次。
- 同一个请求缓存7天；分页进度和限流暂停状态存于 `.catalog-work/requests.sqlite`，下次续跑。
- HTTP 401/403/412/429、B站验证码/风控错误码或非JSON响应会立即停止，并持久化暂停至少24小时。429若指定更长Retry-After则遵守更长时间。
- 网络异常和其他接口错误停止本轮，不连续重试。未做Cookie登录、换IP、伪造指纹、验证码绕过或并发抓取。
- 所有非零接口错误码（包括未识别的错误）均暂停至少24小时；接口不能使用时不连续探测。
- 只运行一个实例。不要删除状态文件来绕过暂停。**无法保证网站永远不限制访问**，低频也可能被拒绝；遇到限制就等暂停期结束，或使用已有本地数据，不换接口绕过限制。
- 公开投稿接口可能要求额外鉴权或变更结构；脚本会停止并保留进度，不承诺该接口始终可用。正常接口迁移使用WBI签名，原有暂停状态保留。

## 核对及导出

`.catalog-work/review.json` 每项包含歌名、歌手、视频标题、BV号和匹配类型。所有条目初始 `approved: false`；即使标题精确匹配也不自动入库。核对歌手、歌曲和完整度后，将确认的条目改为 `true`。

```sh
python tools/build_catalog.py export --review .catalog-work/review.json --output .catalog-work/catalog.next.json
python -m unittest discover -s tools -p 'test_*.py'
```

导出时保留现有21首曲库，按歌曲资料ID合并，不允许直接覆盖正式catalog.json。检查新文件后，再通过Git提交替换正式曲库；服务器按正常插件更新流程采用。当前工具不会自动更新或启用GitHub定时任务。

## 离线继续工作

### 浏览器导出（无需接口采集）

双击仓库根目录的 `浏览器导出工具.html`，按页面说明把导出按钮拖到Chrome书签栏。正常打开已核对歌手的投稿视频页、等待封面加载后，点击书签累积当前页，手动翻页后再点书签继续收集。最后点击面板“下载总清单”，不同歌手合并为一个JSON。进度保存在space.bilibili.com的localStorage，关闭页面仍保留；清空网站数据会丢失进度，建议中途导出备份。工具不自动翻页，不读取Cookie，不请求额外接口。清空操作保留上一份备份，面板可恢复。

双击根目录的 `导入浏览器清单.cmd`，选择一个或多个下载文件。工具离线校验、去重并生成 `.catalog-work/review.json`，不修改正式曲库。命令行也可使用 `python tools/import_browser.py page1.json page2.json`。首版只接受channels.json内三个已核对账号；其他歌手需先核对账号归属。浏览器视频总数不能视作有效歌曲数；匹配结果仍需检查现场版、预告、Remix和同名歌曲。

如果B站拒绝访问，仍可复用 `.catalog-work/videos.json` 运行match/export。也可导入经过核对的本地视频元数据数组（不需要网络）：

```json
[{"bvid":"BV1234567890","title":"视频标题","artist":"kaf","mid":"488970166","cover_url":"https://i0.hdslb.com/实际封面路径","source":"https://space.bilibili.com/488970166"}]
```

示例BV号和封面路径为格式示例，不是实际视频。数据文件保存在工作目录，默认不提交GitHub。控制台只汇总数量和异常，不逐条输出歌词或长日志。

## 更新离线歌曲索引

```sh
python -m pip install -r tools/requirements.txt
python tools/build_catalog.py wiki --source-dir /path/to/kamitsubaki-wiki-site
```

当前环境实测：2026-10-15只请求一次B站投稿接口，返回-799，已停止，没有新增视频；现有21首正式曲库不变。不能将1,039首资料索引误认为1,039首已匹配B站的歌曲。
