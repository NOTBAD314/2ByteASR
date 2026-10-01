"""Reviewed additions to the shared UI catalog (Chinese source, English, Japanese)."""

STRINGS = {
    '校对：{polish} · 断句：{group}': ('Correction: {polish} · Grouping: {group}', '校正：{polish} · 文分割：{group}'),
    '字幕校对使用 AI（可关闭）': ('Use AI for subtitle correction (optional)', '字幕校正に AI を使用（任意）'),
    '关闭后不请求校对模型，也不需要校对 API Key；保留本地转写和文字规则。': ('When disabled, correction sends no AI requests and needs no API key; local transcription and text rules remain active.', 'オフの場合、校正モデルへのリクエストも API キーも不要です。ローカル文字起こしと文字ルールを使用します。'),
    '{stage}（{provider}）缺少 API 密钥。请配置此步骤，或关闭此步骤后重新开始。': ('{stage} ({provider}) is missing an API key. Configure this step, or disable it and start again.', '{stage}（{provider}）の API キーがありません。この工程を設定するか、オフにしてから再実行してください。'),
    '{stage}（{provider}）缺少模型名称。请配置此步骤，或关闭此步骤后重新开始。': ('{stage} ({provider}) is missing a model name. Configure this step, or disable it and start again.', '{stage}（{provider}）のモデル名がありません。この工程を設定するか、オフにしてから再実行してください。'),
    '支持我！': ('Support me!', '開発者を応援！'),
    '支持完全自愿，不影响任何功能的开发和使用。': ('Support is entirely optional and has no effect on the development or use of any feature.', '支援は完全に任意です。支援の有無が、機能の開発や利用に影響することはありません。'),
    '如果兔白字幕帮到了你，而你也愿意支持，会让我开心一整天！': ('If 2ByteASR has helped you and you feel like supporting me, it would make my day!', '兔白字幕がお役に立ち、応援したいと思っていただけたら、とてもうれしいです！'),
    '不支持也完全没关系，感谢你使用兔白字幕！': ('It’s completely fine not to contribute. Thank you for using 2ByteASR!', '支援なしでも、どうぞ気兼ねなくお使いください。兔白字幕をご利用いただき、ありがとうございます！'),
    'PayPal': ('PayPal', 'PayPal'),
    '爱发电': ('Afdian', 'Afdian'),
    '在默认浏览器中打开：{url}': ('Open in your default browser: {url}', '既定のブラウザーで開く：{url}'),
    '永久关闭「支持我」': ('Permanently hide “Support me”', '「開発者を応援」を今後表示しない'),
    '永久关闭「支持我」？': ('Permanently hide “Support me”?', '「開発者を応援」を今後表示しませんか？'),
    '这会让「支持我！」按钮从主页上永久消失。': ('The “Support me!” button will be permanently removed from the home screen.', 'ホーム画面の「開発者を応援！」ボタンが今後表示されなくなります。'),
    '这同样不会影响任何功能的开发和使用。': ('This also has no effect on the development or use of any feature.', '非表示にしても、機能の開発や利用に影響はありません。'),
    '也感谢你使用这款软件！': ('Thank you for using the app!', 'このアプリをご利用いただき、ありがとうございます！'),
    '永久关闭': ('Hide permanently', '今後表示しない'),
    '无法打开浏览器': ('Could not open browser', 'ブラウザーを開けませんでした'),
    '未能打开浏览器。请手动访问：\n{url}': ('Could not open your browser. Please visit this address manually:\n{url}', 'ブラウザーを開けませんでした。次のアドレスを手動で開いてください：\n{url}'),
    '无法保存设置': ('Could not save settings', '設定を保存できませんでした'),
    '未能保存关闭状态，支持入口仍会保留。请稍后重试。': ('Could not save your choice. The support button is still available. Please try again later.', '非表示の設定を保存できなかったため、応援ボタンはそのまま表示されます。後でもう一度お試しください。'),
    '字幕自动避让 ⚠': ('Avoid subtitle overlap ⚠', '字幕の重なり回避 ⚠'),
    '发生遮挡的字幕稳定上移；手动固定位置优先。不会改动文字或时间。': ('Move overlapping subtitles upward. Manual positions take priority. Text and timing stay unchanged.', '字幕が重なる場合は上へ移動します。手動の位置指定を優先し、字幕の内容や時刻は変更しません。'),
    '始 ': ('In ', '開始 '),
    '长 ': ('Len ', '長さ '),
    '角色': ('Speaker', '話者'),
    '单': ('Mono', '単語'),
    '双': ('Dual', '二語'),
    '剪辑': ('Clips', '切り抜き'),
    '选中字幕（{count}）': ('Selected ({count})', '選択中（{count}件）'),
    'Space：播放 / 暂停    Q / W：播放头前 / 后波纹剪切（未锁视频轨）    双击时间轴字幕：直接编辑': ('Space: Play/pause    Q / W: Ripple trim before/after playhead (unlocked video)    Double-click a subtitle to edit', 'Space：再生／一時停止    Q / W：再生ヘッド前／後をリップルトリミング（ロックされていない映像）    字幕をダブルクリックで編集'),
    'C：剃刀（按住拖动看两句预览，松开切开）    V：返回选择': ('C: Razor (drag to preview, release to split)    V: Selection tool', 'C：レーザー（ドラッグでプレビュー、離すと分割）    V：選択ツール'),
    'Enter：确认并继续    Space：重听    Ctrl+Shift+R：重新识别    E：编辑': ('Enter: Confirm and continue    Space: Replay    Ctrl+Shift+R: Transcribe again    E: Edit', 'Enter：確認して次へ    Space：再試聴    Ctrl+Shift+R：再認識    E：編集'),
    '声音诊断': ('Audio Check', '音声診断'),
    '适应窗口': ('Fit', '全体表示'),
    'AI 断句': ('AI Segmentation', 'AI 文分割'),
    '返回兔白字幕': ('Back to Subtitle Studio', '字幕スタジオに戻る'),
    '返回字幕识别': ('Back to Transcription', '字幕認識に戻る'),
    '兔白字幕工程库': ('Subtitle Studio Library', '字幕スタジオのライブラリ'),
    '说话人管理与 MOSS 缓存恢复': ('Manage speakers and recover MOSS results', '話者管理と MOSS のキャッシュ復元'),
    '实际请求：{url}': ('Request URL: {url}', 'リクエスト先：{url}'),
    '填写 Base URL，程序会按所选协议补全请求路径。': ('Enter a base URL. The request path is added for the selected protocol.', 'ベース URL を入力してください。選択したプロトコルのパスが自動で追加されます。'),

    '减少界面动画': ('Reduce interface animations', '画面のアニメーションを減らす'),
    '版本 {value0}': ('Version {value0}', 'バージョン {value0}'),
    '兔白字幕': ('Subtitle Studio', '字幕スタジオ'),
    '2ByteASR  兔白字幕': ('2ByteASR  Subtitle Studio', '2ByteASR  字幕スタジオ'),
    '进入兔白字幕 Studio  →': ('Open Subtitle Studio  →', '字幕スタジオを開く  →'),
    '进入兔白字幕 Studio': ('Open Subtitle Studio', '字幕スタジオを開く'),
    '来自兔白字幕工程': ('From a Subtitle Studio project', '字幕スタジオのプロジェクトから'),
    '最近：{name}': ('Recent: {name}', '最近：{name}'),
    '最近：暂无工程': ('No recent projects', '最近のプロジェクトはありません'),
    '未命名工程': ('Unnamed Project', '無題のプロジェクト'),
    '未命名工程 {number}': ('Unnamed Project {number}', '無題のプロジェクト {number}'),
    '识别结果': ('Recognition Results', '認識結果'),
    '{name} · 识别结果': ('{name} · Recognition Results', '{name} · 認識結果'),
    '说话人区分': ('Speaker Diarization', '話者分離'),
    '说话人管理': ('Speaker Management', '話者管理'),
    '说话人区分：{strategy} · 当前方案：{profile}\n{steps}': ('Speaker diarization: {strategy} · Current plan: {profile}\n{steps}', '話者分離：{strategy} · 現在のプラン：{profile}\n{steps}'),
    '当前默认配置': ('Current defaults', '現在の既定設定'),
    '统一分析音频 → 主转写 → 所选字词对齐/复核': ('Analyze audio → Transcribe → Align/review with selected models', '音声を分析 → 書き起こし → 選択したモデルで単語の時刻調整・確認'),
    'Nemotron 加载 → 分析发声区间 → 同一时间基准匹配字幕 → 审阅说话人/选择主播': ('Load Nemotron → Analyze speech intervals → Match subtitles on the same timeline → Review speakers/select streamer', 'Nemotron を読み込み → 発話区間を分析 → 同じ時間軸で字幕に対応付け → 話者を確認・配信者を選択'),
    'MOSS · 本地 → 匹配字幕 → 审阅身份': ('MOSS · Local → Match subtitles → Review speakers', 'MOSS · ローカル → 字幕に対応付け → 話者を確認'),
    'ECAPA · 本地 → 匹配字幕 → 审阅身份': ('ECAPA · Local → Match subtitles → Review speakers', 'ECAPA · ローカル → 字幕に対応付け → 話者を確認'),
    '供应商原生标签 → 匹配字幕 → 审阅身份': ('Provider speaker labels → Match subtitles → Review speakers', 'プロバイダーの話者ラベル → 字幕に対応付け → 話者を確認'),
    'Filetrans 原生标签 → 匹配字幕 → 审阅身份': ('Filetrans speaker labels → Match subtitles → Review speakers', 'Filetrans の話者ラベル → 字幕に対応付け → 話者を確認'),
    'MOSS · 本地': ('MOSS · Local', 'MOSS · ローカル'),
    'ECAPA · 本地': ('ECAPA · Local', 'ECAPA · ローカル'),
    'Nemotron 3 · 本地': ('Nemotron 3 · Local', 'Nemotron 3 · ローカル'),
    '供应商原生标签': ('Provider speaker labels', 'プロバイダーの話者ラベル'),
    'Filetrans 原生标签': ('Filetrans speaker labels', 'Filetrans の話者ラベル'),
    '已关闭 · 统一字幕轨': ('Off · Single subtitle track', 'オフ · 単一の字幕トラック'),
    '保留统一字幕轨，不运行额外说话人模型': ('Keep a single subtitle track; no additional speaker model', '字幕を単一トラックに保持し、追加の話者モデルは使用しません'),
    '继续编辑': ('Continue Editing', '編集を続ける'),
    '可继续': ('Ready to edit', '編集可能'),
    '可打开': ('Available', '利用可能'),
    '素材离线': ('Media offline', 'メディアがオフライン'),
    '工程文件已移动': ('Project file missing', 'プロジェクトファイルが見つかりません'),
    '无源媒体': ('No source media', '元のメディアなし'),
    '{count} 条字幕': ('Subtitles: {count}', '字幕 {count} 件'),
    'AI 设计': ('AI Design', 'AI デザイン'),
    'AI设计': ('AI Design', 'AI デザイン'),
    '样式': ('Style', 'スタイル'),
    '视频': ('Video', '動画'),
    '剪辑助手': ('Clip Assistant', 'クリップアシスタント'),
    '素材': ('Media', 'メディア'),
    '全部': ('All', 'すべて'),
    '建议确认': ('Review Suggested', '確認を推奨'),
    '需要检查': ('Needs Review', '要確認'),
    '仅需要检查': ('Needs Review Only', '要確認のみ'),
    '示例字幕 Aa 123': ('Sample Subtitles Aa 123', '字幕サンプル Aa 123'),
    '纯色': ('Solid Color', '単色'),
    '纯色 {color}': ('Solid {color}', '単色 {color}'),
    '已关闭': ('Off', 'オフ'),
    '开启': ('On', 'オン'),
    '不透明度': ('Opacity', '不透明度'),
    '距离': ('Distance', '距離'),
    '模糊': ('Blur', 'ぼかし'),
    '不透明度 {opacity:g}% · 距离 {distance:.0f}px · 模糊 {blur:g}px': ('Opacity {opacity:g}% · Distance {distance:.0f}px · Blur {blur:g}px', '不透明度 {opacity:g}% · 距離 {distance:.0f}px · ぼかし {blur:g}px'),
    '{kind} · {count}色 · {angle:.0f}°': ('{kind} · {count} colors · {angle:.0f}°', '{kind} · {count}色 · {angle:.0f}°'),
    '黑色 · {shadow:g}': ('Black · {shadow:g}', '黒 · {shadow:g}'),
    '双层 {color} · {width:g} + {second_color} · {second_width:g}': ('Double {color} · {width:g} + {second_color} · {second_width:g}', '二重 {color} · {width:g} + {second_color} · {second_width:g}'),
    '字幕自动避让': ('Avoid Subtitle Overlap', '字幕の重なりを自動回避'),
    '入点 I': ('In I', 'イン I'),
    '出点 O': ('Out O', 'アウト O'),
    '工程开头': ('Project Start', 'プロジェクトの先頭'),
    '工程结尾': ('Project End', 'プロジェクトの末尾'),
    '跳到': ('Go', '移動'),
    '清除范围': ('Clear Range', '範囲を解除'),
    '时长 {duration} · 出点帧不包含': ('Duration {duration} · Out frame excluded', '長さ {duration} · アウト点のフレームは含みません'),
    '声音诊断': ('Audio Diagnostics', '音声診断'),
    '主画面·底层': ('Main video · Bottom', 'メイン映像・最下層'),
    '{track}  波形': ('{track}  Waveform', '{track}  波形'),
    '波形': ('Waveform', '波形'),
    '选择默认工程目录': ('Choose Default Project Folder', '既定のプロジェクト保存先を選択'),
    '默认工程保存位置': ('Default project location', '既定のプロジェクト保存先'),
    '首次保存帧时选择': ('Choose when saving the first frame', '最初のフレーム保存時に選択'),
    '自动生成工程封面': ('Generate project covers automatically', 'プロジェクトのカバー画像を自動生成'),
    '打开工程时恢复上次布局': ('Restore layout when opening a project', 'プロジェクトを開くときに前回のレイアウトを復元'),
    '减少过渡动画': ('Reduce transition animations', '画面切り替えのアニメーションを減らす'),
    '保存当前帧的位置；不再固定到视频所在目录。': ('Location for saved frames; independent of the video folder.', 'フレームの保存先です。動画のフォルダーとは別に指定できます。'),
    '30 秒': ('30 seconds', '30 秒'),
    '1 分钟': ('1 minute', '1 分'),
    '2 分钟': ('2 minutes', '2 分'),
    '5 分钟': ('5 minutes', '5 分'),
    'Studio 界面': ('Studio interface', 'Studio の画面'),
    '恢复默认的面板位置与尺寸': ('Restore default panel positions and sizes', 'パネルの位置とサイズを既定値に戻す'),
    '未保存的更改': ('Unsaved changes', '未保存の変更'),
    '应用这些设置更改？': ('Apply these settings changes?', '設定の変更を適用しますか？'),
    '重置布局': ('Reset Layout', 'レイアウトをリセット'),
}



# Bound status messages
STRINGS.update({
    '{value0} 条字幕主题异常 · 使用基础预览': ('{value0} subtitle themes unavailable · Using basic preview', '字幕テーマ {value0} 件が使用不可 · 基本プレビューを使用中'),
    '字幕合成暂不可用 · 特效字幕等待恢复': ('Subtitle compositor unavailable · Waiting to restore effects', '字幕の合成を利用できません · エフェクトの復旧を待機中'),
    '左侧当前色，右侧上次颜色（点击恢复）': ('Current color on the left; previous color on the right (click to restore)', '左は現在の色、右は前回の色（クリックで戻す）'),
    '从屏幕取色': ('Pick a color from the screen', '画面から色を取得'),
    '高级': ('Advanced', '詳細'),
    '请输入 6 位 HEX 颜色，例如 #FF7100': ('Enter a 6-digit HEX color, e.g. #FF7100', '6桁の HEX カラーを入力してください（例：#FF7100）'),
    '拾': ('Pick', '取得'),
    '文件': ('File', 'ファイル'),
    '勾选时：拖动角点、边柄或修改宽高都保持比例。取消后可单独拉宽或拉高。': ('When checked, corner/edge dragging and width/height changes keep the aspect ratio. Uncheck to stretch freely.', 'オンにすると、角や辺のドラッグ、幅・高さの変更時に縦横比を維持します。オフにすると個別に伸縮できます。'),
    '输入中文标题；Enter 换行': ('Enter a title; Enter inserts a line break', 'タイトルを入力（Enter で改行）'),
    '{value0}{name} · 2ByteASR 封面': ('{value0}{name} · 2ByteASR Cover', '{value0}{name} · 2ByteASR サムネイル'),
    '底图已更新至 {value0:.3f} 秒；标题与贴图保留，可撤销。': ('Background updated to {value0:.3f} s. Titles and overlays were kept. You can undo this.', '背景を {value0:.3f} 秒のフレームに更新しました。タイトルと画像は保持され、元に戻せます。'),
    '保存为模板': ('Save as Template', 'テンプレートとして保存'),
    '导出封面图片': ('Export Cover Image', 'サムネイル画像を書き出し'),
    '上次目录已不可用；请在文件窗口选择新目录。': ('The previous folder is unavailable. Choose a new folder in the file dialog.', '前回のフォルダーを利用できません。ファイル画面で別のフォルダーを選択してください。'),
    '{label}成功 · {elapsed:.3f} 秒': ('{label} succeeded · {elapsed:.3f} s', '{label}完了 · {elapsed:.3f} 秒'),
    '文件操作正在完成，请稍候。': ('A file operation is finishing. Please wait.', 'ファイル操作を完了しています。しばらくお待ちください。'),
    '已导出 {value0} × {value1} · {value2}': ('Exported {value0} × {value1} · {value2}', '書き出し完了 {value0} × {value1} · {value2}'),
    '文件操作正在完成，请稍候再关闭。': ('A file operation is finishing. Please wait before closing.', 'ファイル操作を完了しています。完了してから閉じてください。'),
    '查看 {value0:.0f}%': ('View {value0:.0f}%', '表示 {value0:.0f}%'),
    '搜索中文或英文字体名': ('Search font names in Chinese or English', '中国語名または英語名でフォントを検索'),
    '封面工作台 · 本地 GIMP': ('Cover Studio · Local GIMP', 'サムネイルスタジオ · ローカル GIMP'),
    '更多': ('More', 'その他'),
    '模板主标题：可在此快速修改，也可在 GIMP 中直接编辑': ('Template title: edit here or directly in GIMP', 'テンプレートのタイトル：ここでも GIMP でも編集できます'),
    '双击此处进入 GIMP 原生编辑': ('Double-click to edit in GIMP', 'ダブルクリックで GIMP で編集'),
    'PSD 导入：原件保留，文字外观需检查；详细差异见提示。': ('PSD imported. The original was kept. Check the text appearance; see the notice for differences.', 'PSD を読み込みました。原本は保持されています。文字の見た目と、通知に記載された差分を確認してください。'),
    '正在保存活文档并验证 XCF…': ('Saving the open document and validating the XCF…', '開いている文書を保存して XCF を検証中…'),
    '正在从 GIMP 活文档导出…': ('Exporting the open GIMP document…', 'GIMP で開いている文書を書き出し中…'),
    '已重新连接仍在运行的本地 GIMP 文档。': ('Reconnected to the local GIMP document that is still open.', 'ローカルの GIMP で開いている文書に再接続しました。'),
    '发现未完成草稿。通过“更多 → 恢复草稿”选择文档；恢复不会覆盖手动保存或模板。': ('An unfinished draft was found. Choose More → Recover Draft. Recovery will not overwrite saved files or templates.', '未完成の下書きが見つかりました。「その他 → 下書きを復元」で選択してください。保存済みファイルやテンプレートは上書きしません。'),
    '本次没有 Studio 冻结帧；可从 Studio 制作封面或添加本地图片。': ('No captured Studio frame is available. Create a cover from Studio or add a local image.', 'Studio で取得したフレームがありません。Studio からサムネイルを作成するか、画像を追加してください。'),
    '请通过“更多 → 设置模板槽位”指定可替换底图。': ('Choose More → Set Template Slots to select a replaceable background.', '「その他 → テンプレートの置換箇所を設定」で、差し替える背景を指定してください。'),
    '当前文档还没有模板母版，请先保存为新模板。': ('This document has no template master yet. Save it as a new template first.', 'この文書にはテンプレートの原本がありません。まず新しいテンプレートとして保存してください。'),
    '模板槽位与换图方式': ('Template Slots and Image Replacement', 'テンプレートの置換箇所と画像の差し替え'),
    '没有可恢复的未完成草稿。': ('No unfinished draft is available to recover.', '復元できる未完成の下書きはありません。'),
    '本地字体已刷新，可在 GIMP 字体列表选择；XCF 不嵌入字体。': ("Local fonts refreshed. Select them in GIMP's font list; XCF files do not embed fonts.", 'ローカルフォントを更新しました。GIMP のフォント一覧で選択できます。XCF にフォントは埋め込まれません。'),
    '已由校验通过的旧 PSD 元数据重建可编辑文字。检查后选“更新此模板”保存 XCF；原 PSD 已备份并保留。': ('Editable text restored from verified legacy PSD metadata. Review it and choose Update This Template to save the XCF. The original PSD was backed up and kept.', '検証済みの旧 PSD メタデータから編集可能な文字を復元しました。確認後「このテンプレートを更新」で XCF を保存してください。元の PSD はバックアップして保持しています。'),
    '模板文件已作为新文档打开。检查效果并设置槽位，再选择“保存为模板”。': ('Template opened as a new document. Review it, set replacement slots, then choose Save as Template.', 'テンプレートを新規文書として開きました。見た目と置換箇所を確認し、「テンプレートとして保存」を選択してください。'),
    '此旧 PSD 的原始文字/样式元数据校验通过，已重建为 GIMP 可编辑图层；原 PSD 保留。': ('Legacy PSD text and style metadata verified and restored as editable GIMP layers. The original PSD was kept.', '旧 PSD の文字・スタイル情報を検証し、GIMP の編集可能なレイヤーとして復元しました。元の PSD は保持しています。'),
    '制作封面': ('Create Cover', 'サムネイルを作成'),
    '本地封面编辑：当前截图、新建封面或选择模板': ('Local cover editor: current frame, new cover, or template', 'ローカルでサムネイルを編集：現在のフレーム、新規作成、テンプレート'),
    '请定位新画面，再点“制作封面 → 当前截图”更新此封面的底图。': ('Seek to a new frame, then choose Create Cover → Current Frame to update the background.', '新しいフレームに移動し、「サムネイルを作成 → 現在のフレーム」で背景を更新してください。'),
    '正在制作封面：后台读取高清底图…': ('Creating cover: loading the full-resolution background…', 'サムネイルを作成中：高解像度の背景を読み込み中…'),
    '正在准备已冻结的高清底图…': ('Preparing the captured full-resolution background…', '取得した高解像度の背景を準備中…'),
    '当前没有可截图的视频；可选择“新建封面”或“选择模板”。': ('No video frame is available. Choose New Cover or Choose Template.', '取得できる動画フレームがありません。「新規サムネイル」または「テンプレートを選択」を使用してください。'),
    '封面底图已冻结；字幕如已包含，则为图片像素。': ('Background captured. Any included subtitles are part of the image pixels.', '背景を取得しました。映り込んだ字幕は画像の一部として保存されます。'),
    '工程已切换，已丢弃旧取帧结果。': ('Project changed; the previous frame capture was discarded.', 'プロジェクトが切り替わったため、前のフレーム取得結果を破棄しました。'),
    '封面已关闭或切换，已丢弃旧取帧结果。': ('Cover closed or changed; the previous frame capture was discarded.', 'サムネイルが閉じられたか切り替わったため、前のフレーム取得結果を破棄しました。'),
    '封面模板': ('Cover Templates', 'サムネイルのテンプレート'),
    '搜索主播、系列或模板名称': ('Search streamer, series, or template name', '配信者、シリーズ、テンプレート名で検索'),
    '使用当前视频帧作为底图（保留模板标题和贴图）': ('Use the current video frame as the background (keep template titles and overlays)', '現在の動画フレームを背景に使用（テンプレートのタイトルと画像を保持）'),
    '已收到素材，正在检查…': ('Media received. Checking…', 'メディアを受け取りました。確認中…'),
    '已接收 {value0} 个素材，已跳过 {value1} 个文件': ('Media accepted: {value0} · Files skipped: {value1}', '受け付けたメディア：{value0} 件 · スキップ：{value1} ファイル'),
    '搜索过程、查询词或来源': ('Search activity, queries, or sources', '処理、検索語、参照元を検索'),
    '2ByteASR · 成片压制': ('2ByteASR · Video Encoding', '2ByteASR · 動画エンコード'),
    '播放成片预览': ('Preview Encoded Video', '書き出した動画をプレビュー'),
    '播放成片': ('Play Video', '動画を再生'),
    '最终文件的容器平均码率（含视频、音频及封装开销），以文件字节数 × 8 ÷ 实际媒体时长校验。': ('Average container bitrate of the final file, including video, audio, and container overhead. Verified as file bytes × 8 ÷ actual media duration.', '最終ファイルの平均ビットレートです。映像・音声・コンテナー情報を含み、ファイルのバイト数 × 8 ÷ 実際の長さで確認します。'),
    '保存当前帧': ('Save Current Frame', '現在のフレームを保存'),
    '保存工程画布原分辨率图片（Ctrl+Alt+F）': ('Save an image at the project canvas resolution (Ctrl+Alt+F)', 'プロジェクトのキャンバス解像度で画像を保存（Ctrl+Alt+F）'),
    '正在后台保存当前帧…': ('Saving the current frame in the background…', '現在のフレームをバックグラウンドで保存中…'),
    '正在保存已捕获的帧，请稍候。': ('Saving the captured frame. Please wait.', '取得したフレームを保存中です。しばらくお待ちください。'),
    '原保存帧目录不可用，请重新选择。': ('The previous frame folder is unavailable. Choose another folder.', '前回のフレーム保存先を利用できません。別のフォルダーを選択してください。'),
    '{value0}预览｜{value1}': ('{value0} Preview | {value1}', '{value0}プレビュー｜{value1}'),
    '筛选词条 / 别名 / 依据…': ('Filter terms, aliases, or evidence…', '用語、別名、根拠を絞り込み…'),
    '总勾选 {checked}；当前筛选中 {inside}/{total}；筛选外 {value3}': ('Selected: {checked} · In current filter: {inside}/{total} · Outside filter: {value3}', '選択済み：{checked} 件 · 表示中：{inside}/{total} 件 · 絞り込み対象外：{value3} 件'),
    '{value0} / {value1} · 总耗时 {value2}s · 距真实事件 {value3}s · {value4} 候选': ('{value0} / {value1} · Elapsed {value2}s · Last event {value3}s ago · {value4} candidates', '{value0} / {value1} · 経過 {value2}秒 · 最終イベントから {value3}秒 · 候補 {value4} 件'),
    '已就绪 {value0} 条快照': ('Snapshots ready: {value0}', '準備済みのスナップショット：{value0} 件'),
    '更新记录｜{value0}': ('Update History | {value0}', '更新履歴｜{value0}'),
    '正在取消…后续游戏将跳过。': ('Cancelling… Remaining games will be skipped.', 'キャンセル中… 残りのゲームはスキップします。'),
    '[{game}] 检索来源…': ('[{game}] Searching sources…', '[{game}] 参照元を検索中…'),
    '批量完成：成功 {value0} · 失败 {value1} · 跳过 {value2}。已保存项已入库；双击结果可查看候选和重试失败项。': ('Batch finished: {value0} succeeded · {value1} failed · {value2} skipped. Saved items are in the library. Double-click a result to review candidates or retry failures.', '一括処理完了：成功 {value0} 件 · 失敗 {value1} 件 · スキップ {value2} 件。保存済みの項目は登録されています。結果をダブルクリックして候補の確認や再試行ができます。'),
    '从任务栏移除（不影响已入库结果）': ('Remove from task list (keep saved results)', 'タスク一覧から削除（登録済みの結果は保持）'),
    '已撤销本次合并中的 {removed} 条映射。': ('Removed {removed} mappings added by this merge.', '今回の統合で追加した対応関係 {removed} 件を取り消しました。'),
    '请先勾选要更新的游戏。': ('Select the games to update first.', '更新するゲームを選択してください。'),
    '进入字幕工作台': ('Open Subtitle Studio', '字幕スタジオを開く'),
    '使用哪个 AI 执行本次检索整理（复用已配置的登录/密钥，不改动全局设置）': ('AI for this search and organization task (uses configured sign-in or keys without changing global settings)', 'この検索・整理に使用する AI（設定済みのログインやキーを使用し、全体設定は変更しません）'),
    '清单式补全：检索官方目录页 → 程序提取名称 → 分批整理 → 社区用语补搜；适合空白/大缺口词库': ('Catalog completion: search official catalogs → extract names → organize in batches → search community terms. Best for empty or incomplete libraries.', '一覧から補完：公式カタログを検索 → 名称を抽出 → 分割して整理 → コミュニティ用語を追加検索。空の辞書や不足の多い辞書向けです。'),
    '版本增量：检索最近版本新增与高频术语（单轮，适合已建库词库）': ('Version update: search new and common terms from recent releases (one pass, for existing libraries)', '差分更新：最近のバージョンで追加された用語や頻出用語を検索（1回の処理、既存の辞書向け）'),
    '批量接受所选建议并加入当前项目关联词库': ("Accept selected suggestions and add them to this project's linked term library", '選択した候補を採用し、このプロジェクトに関連付けた用語集に追加'),
    '批量接受所选建议并加入当前 Profile 使用的词库': ("Accept selected suggestions and add them to the current profile's term library", '選択した候補を採用し、現在のプロファイルの用語集に追加'),
    '{value0} 条待学习': ('Terms to learn: {value0}', '学習待ち：{value0} 件'),
    '要从术语库中删除《{game_name}》以及它的术语吗？\n内置词库文件不会被修改。': ('Delete “{game_name}” and its terms from the library?\nBuilt-in library files will not be changed.', '「{game_name}」とその用語を削除しますか？\n内蔵辞書ファイルは変更しません。'),
    '确定删除「{label}」吗？': ('Delete “{label}”?', '「{label}」を削除しますか？'),
    '批量导入术语｜{game_name}': ('Bulk Term Import | {game_name}', '用語の一括インポート｜{game_name}'),
    '「{game}」更新失败（{code}）：{message}': ('Update failed for “{game}” ({code}): {message}', '「{game}」の更新に失敗しました（{code}）：{message}'),
    '没有符合筛选条件的词条': ('No terms match the filter', '条件に一致する用語はありません'),
    '调整搜索词或筛选条件，即可看到全部词条。': ('Change the search or filters to see more terms.', '検索語や条件を変更すると、他の用語を表示できます。'),
    '让识别更懂你的游戏': ('Help recognition understand your game', 'ゲームの用語を認識に反映'),
    '加入角色名、地点和专有词，可以减少同音词误识别。': ('Add character names, places, and specialized terms to reduce homophone errors.', 'キャラクター名、地名、専門用語を追加すると、同音語の誤認識を減らせます。'),
    '智能建词｜{game_name}': ('AI Term Builder | {game_name}', 'AI 用語集作成｜{game_name}'),
    '● 支持联网检索': ('● Web search supported', '● ウェブ検索に対応'),
    '○ 无服务端搜索': ('○ No server-side search', '○ サーバー側の検索なし'),
    '{value0}；仍可用智能建词的本地资料整理。': ('{value0}; local reference organization is still available in AI Term Builder.', '{value0}。AI 用語集作成でローカル資料の整理は利用できます。'),
    '联网更新当前词库': ('Update Current Library Online', '現在の用語集をオンライン更新'),
    '完整建库…': ('Build Complete Library…', '用語集を一括作成…'),
    '联网更新预览｜{game_name}': ('Online Update Preview | {game_name}', 'オンライン更新のプレビュー｜{game_name}'),
    '批量更新游戏词库': ('Update Game Libraries in Bulk', 'ゲーム用語集を一括更新'),
    '将 ChatGPT / DeepSeek / Gemini 返回的 TSV 粘贴到这里。\n列顺序：标准词  分类  别名或常见错写': ('Paste TSV returned by ChatGPT / DeepSeek / Gemini here.\nColumn order: canonical term, category, aliases or common misspellings', 'ChatGPT / DeepSeek / Gemini の TSV を貼り付けてください。\n列の順序：正式名称、分類、別名またはよくある誤表記'),
    '已选择：AI 建词 TSV': ('Selected: AI-generated term TSV', '選択済み：AI 作成の用語 TSV'),
    '解析并预览': ('Parse and Preview', '解析してプレビュー'),
    '模型存储管理': ('Model Storage', 'モデルの保存先管理'),
    '预计下载 {expected}    模型文件 {actual}    运行环境 {runtime}\n{value3}': ('Download estimate {expected}    Model files {actual}    Runtime {runtime}\n{value3}', 'ダウンロード予定 {expected}    モデル {actual}    実行環境 {runtime}\n{value3}'),
    '扫描中': ('Scanning', 'スキャン中'),
    '体积 {size_text}': ('Size {size_text}', 'サイズ {size_text}'),
    '关闭下载窗口': ('Close Download Window', 'ダウンロード画面を閉じる'),
    '{state} · 已用 {value1} 秒 · 最后日志：{age}': ('{state} · Elapsed {value1} s · Last log: {age}', '{state} · 経過 {value1} 秒 · 最終ログ：{age}'),
    '<a href="{source_url}" style="color:#4b7043; text-decoration:none;">查看完整官方 Benchmark ↗</a>': ('<a href="{source_url}" style="color:#4b7043; text-decoration:none;">View full official benchmark ↗</a>', '<a href="{source_url}" style="color:#4b7043; text-decoration:none;">公式ベンチマークの全結果 ↗</a>'),
    '将在下一次识别中分析谁在什么时候说话，不负责转写文字，也不会自动修改已有字幕。\n修改范围：当前方案；在途任务继续使用启动快照。': ('The next recognition task will analyze who speaks when. This does not transcribe text or change existing subtitles.\nChanges apply to the current plan; running tasks keep their startup settings.', '次の認識で、誰がいつ話したかを分析します。文字の書き起こしや既存字幕の変更は行いません。\n現在のプランに適用され、実行中のタスクは開始時の設定を維持します。'),
    '{value0} · 技术说明': ('{value0} · Technical Notes', '{value0} · 技術情報'),
    '跳过 {label}：{value1}': ('Skipped {label}: {value1}', '{label} をスキップ：{value1}'),
    '工程时间：时:分:秒.毫秒；留空采用工程边界': ('Project time: hh:mm:ss.milliseconds. Leave blank to use the project boundary.', 'プロジェクト時刻：時:分:秒.ミリ秒。空欄の場合はプロジェクトの端を使用します。'),
    '已保存的 AI 字幕设计': ('Saved AI Subtitle Designs', '保存済みの AI 字幕デザイン'),
    '静态字幕 · 预览与导出共用字形布局': ('Static subtitles · Preview and export share the same glyph layout', '静止字幕 · プレビューと書き出しで同じ字形配置を使用'),
    '开发诊断渲染已隔离': ('Diagnostic render isolated', '診断レンダリングを隔離しました'),
    '诊断任务不会接管前景': ('Diagnostic tasks will not replace the foreground preview', '診断タスクは現在のプレビューを置き換えません'),
    '预览缓存不可读': ('Preview cache is unreadable', 'プレビューキャッシュを読み取れません'),
    '⚡ 实时预览已就绪': ('⚡ Live preview ready', '⚡ リアルタイムプレビュー準備完了'),
    '预览不可用 · 使用 Studio 近似预览': ("Preview unavailable · Using Studio's approximate preview", 'プレビューを利用できません · Studio の簡易プレビューを使用中'),
    '复杂视觉 · 近似预览已就绪…': ('Complex visuals · Approximate preview ready…', '複雑なビジュアル · 簡易プレビュー準備完了…'),
    '⚡ LIVE 近似预览中 · 高保真预览后台准备中': ('⚡ LIVE approximate preview · Preparing full-fidelity preview', '⚡ LIVE 簡易プレビュー · 高精細プレビューを準備中'),
    '⚡ 复杂视觉 · 正在准备实时预览…': ('⚡ Complex visuals · Preparing live preview…', '⚡ 複雑なビジュアル · リアルタイムプレビューを準備中…'),
    '⚡ LIVE 已就绪 · 高保真预览后台准备中': ('⚡ LIVE ready · Preparing full-fidelity preview', '⚡ LIVE 準備完了 · 高精細プレビューを準備中'),
    '⚡ LIVE 播放中 · 高保真帧已在后台就绪': ('⚡ LIVE playing · Full-fidelity frames ready in background', '⚡ LIVE 再生中 · 高精細フレームの準備完了'),
    '微调设计 · 方案 {value0}': ('Refine Design · Option {value0}', 'デザインを調整 · 案 {value0}'),
    '输入修改要求…': ('Describe your changes…', '変更内容を入力…'),
    '生成修订版': ('Generate Revision', '修正版を生成'),
    '取消生成': ('Cancel Generation', '生成をキャンセル'),
    '正在生成视觉方案': ('Generating visual designs', 'ビジュアル案を生成中'),
    '正在构建并校验三套视觉方案': ('Building and validating three visual designs', '3つのビジュアル案を作成・検証中'),
    '取消登录': ('Cancel Sign-in', 'ログインをキャンセル'),
    '取消检测': ('Cancel Detection', '検出をキャンセル'),
    '正在加载六秒动画…': ('Loading the six-second animation…', '6秒のアニメーションを読み込み中…'),
    '正在微调方案 {value0} …': ('Refining option {value0}…', '案 {value0} を調整中…'),
    '方案 {value0} 已更新为 Version {value1}{suffix}': ('Option {value0} updated to Version {value1}{suffix}', '案 {value0} を Version {value1}{suffix} に更新しました'),
    '微调失败：{message}': ('Refinement failed: {message}', '調整に失敗しました：{message}'),
    '方案 {value0} 已恢复上一版': ('Previous version restored for option {value0}', '案 {value0} を前のバージョンに戻しました'),
    'AI 原始 JSON · 调试': ('Raw AI JSON · Debug', 'AI の元の JSON · デバッグ'),
    '重新生成': ('Regenerate', '再生成'),
    '当前设计对象：未选择字幕（视频片段不能生成字幕设计）': ('Design target: no subtitle selected (video clips cannot be used for subtitle design)', 'デザイン対象：字幕が未選択です（動画クリップには字幕デザインを生成できません）'),
    '当前设计对象：{value0} · {value1:.3f}–{value2:.3f} 秒': ('Design target: {value0} · {value1:.3f}–{value2:.3f} s', 'デザイン対象：{value0} · {value1:.3f}–{value2:.3f} 秒'),
    '多选时为当前活动字幕；应用范围由下方选项决定。': ('With multiple items selected, this is the active subtitle. Choose the apply scope below.', '複数選択時は、現在アクティブな字幕が対象です。適用範囲は下の項目で指定します。'),
    '取消中…': ('Cancelling…', 'キャンセル中…'),
    '正在取消 Provider 请求': ('Cancelling the provider request', 'プロバイダーへのリクエストをキャンセル中'),
    '设计文字与框线 → 生成候选 → 实际动画预览': ('Design text and borders → Generate options → Preview actual animation', '文字と枠をデザイン → 候補を生成 → 実際のアニメーションを確認'),
    '方案 {value0} · {concept_name}': ('Option {value0} · {concept_name}', '案 {value0} · {concept_name}'),
    '上一轮微调仍在进行': ('The previous refinement is still running', '前の調整を実行中です'),
    '该方案没有 VisualDesignGraph，无法微调': ('This option has no VisualDesignGraph and cannot be refined', 'この案には VisualDesignGraph がないため調整できません'),
    '暂时无法生成预览；可重试生成方案': ('Preview could not be generated. Try generating the design again.', 'プレビューを生成できません。デザインの生成を再試行してください。'),
    '文字颜色 {value0}': ('Text color {value0}', '文字色 {value0}'),
    '无动效': ('No animation', 'アニメーションなし'),
    '实时动效暂不可用：{exc}': ('Live animation unavailable: {exc}', 'リアルタイムアニメーションを利用できません：{exc}'),
    'LIVE 编译场景播放完成': ('LIVE scene playback finished', 'LIVE シーンの再生が完了しました'),
    'AI 生成进度': ('AI Generation Progress', 'AI 生成の進行状況'),
    '模型实时输出…': ('Live model output…', 'モデルの出力を受信中…'),
    '正在连接 Provider…': ('Connecting to provider…', 'プロバイダーに接続中…'),
    '运行 JSON 已记录：{trace_path}': ('Run JSON saved: {trace_path}', '実行 JSON を保存しました：{trace_path}'),
    '已耗时 {minutes}:{seconds:02d} · 预计剩余 {r_minutes}:{r_seconds:02d}': ('Elapsed {minutes}:{seconds:02d} · Estimated remaining {r_minutes}:{r_seconds:02d}', '経過 {minutes}:{seconds:02d} · 残り時間の目安 {r_minutes}:{r_seconds:02d}'),
    '已耗时 {minutes}:{seconds:02d} · 以实际阶段和候选结果为准': ('Elapsed {minutes}:{seconds:02d} · Progress follows actual stages and results', '経過 {minutes}:{seconds:02d} · 実際の処理段階と候補の結果を表示します'),
    '预览更新失败: {message}': ('Preview update failed: {message}', 'プレビューの更新に失敗しました：{message}'),
    '当前没有可编辑字幕': ('No editable subtitle available', '編集できる字幕はありません'),
    '轨道已锁定，请先解锁': ('Track is locked. Unlock it first.', 'トラックはロックされています。先に解除してください。'),
    'Q/W 边界编辑请只选中一条字幕': ('Select a single subtitle to edit a boundary with Q/W', 'Q/W で境界を編集するには、字幕を1つだけ選択してください'),
    '字幕时长不能小于 {MIN_CUE_DURATION_MS} 毫秒': ('Subtitle duration must be at least {MIN_CUE_DURATION_MS} ms', '字幕の長さは {MIN_CUE_DURATION_MS} ミリ秒以上必要です'),
    '字幕跨剪辑边界，无法无损调整时间': ('Subtitle crosses an edit boundary; its timing cannot be adjusted without loss', '字幕が編集境界をまたいでいるため、内容を保ったまま時刻を調整できません'),
    '切点位于首个或末个词内，无法分成两段文字': ('The cut falls inside the first or last word; the text cannot be split into two parts', '切断点が最初または最後の単語内にあるため、文字を2つに分割できません'),
    '切点跨剪辑边界，无法无损映射到原字幕': ('The cut crosses an edit boundary and cannot be mapped to the original subtitle without loss', '切断点が編集境界をまたぎ、元の字幕に正確に対応付けられません'),
    '分析已取消': ('Analysis cancelled', '分析をキャンセルしました'),
    '工程已修改，已丢弃过期分析，请重新分析。': ('The project changed. Outdated analysis was discarded; please analyze again.', 'プロジェクトが変更されたため、古い分析結果を破棄しました。再分析してください。'),
    '选择自定义文件夹': ('Choose Custom Folder', '保存先フォルダーを選択'),
    '尚未选择自定义文件夹': ('No custom folder selected', '保存先フォルダーが未選択です'),
    '正在写入并回读验证…': ('Writing and verifying saved files…', 'ファイルを書き込み、読み直して検証中…'),
    '已导出并验证 {value0} 个文件 · {destination_reason}': ('Files exported and verified: {value0} · {destination_reason}', '書き出し・検証済み：{value0} ファイル · {destination_reason}'),
    '已复制 {value0} 个字幕路径': ('Subtitle paths copied: {value0}', '字幕のパスを {value0} 件コピーしました'),
    '管理导出预设': ('Manage Export Presets', '書き出しプリセットを管理'),
    '管理预设：保存、另存为、删除': ('Manage presets: save, save as, delete', 'プリセットの管理：保存、名前を付けて保存、削除'),
    '专家编码设置': ('Advanced Encoding Settings', '詳細エンコード設定'),
    '控制编码兼容性。通常保持自动即可。': ('Controls encoding compatibility. Auto is usually recommended.', 'エンコードの互換性を指定します。通常は自動を使用してください。'),
    '限制解码复杂度。除特殊播放设备外建议自动。': ('Limits decoding complexity. Auto is recommended unless a playback device requires otherwise.', 'デコードの複雑さを制限します。特定の再生機器で必要な場合以外は、自動を推奨します。'),
    '影响颜色格式和兼容性。yuv420p 兼容性最好。': ('Affects color format and compatibility. yuv420p offers the widest compatibility.', '色形式と互換性に影響します。yuv420p が最も広く対応しています。'),
    '关键帧间隔。一般无需手动修改。': ('Keyframe interval. Usually no manual change is needed.', 'キーフレームの間隔です。通常は変更する必要はありません。'),
    '▾ 运行详情': ('▾ Run Details', '▾ 実行の詳細'),
    '当前将使用：{friendly}': ('Will use: {friendly}', '使用する設定：{friendly}'),
    '已保存导出预设': ('Export preset saved', '書き出しプリセットを保存しました'),
    '已另存为「{label}」': ('Saved as “{label}”', '「{label}」として保存しました'),
    '输出：{value0}': ('Output: {value0}', '出力先：{value0}'),
    '{resolution_text} · {fps_text}\n{value2} · {value3} · {value4}\n{value5} · 字幕烧录 · 范围 {value6}': ('{resolution_text} · {fps_text}\n{value2} · {value3} · {value4}\n{value5} · Burned-in subtitles · Range {value6}', '{resolution_text} · {fps_text}\n{value2} · {value3} · {value4}\n{value5} · 字幕を焼き込み · 範囲 {value6}'),
    '预计文件大小：~{value0} MB': ('Estimated file size: ~{value0} MB', 'ファイルサイズの目安：約 {value0} MB'),
    '等待首个处理帧': ('Waiting for the first processed frame', '最初のフレームの処理を待機中'),
    '输出：{output}': ('Output: {output}', '出力先：{output}'),
    '总进度 {value0}% · {label} {stage_copy}': ('Overall {value0}% · {label} {stage_copy}', '全体 {value0}% · {label} {stage_copy}'),
    '当前步骤  ·  {active} · 运行中': ('Current step · {active} · Running', '現在の処理 · {active} · 実行中'),
    '失败阶段：{phase}\n{value1}\n请返回设置修正后重试；完整诊断可在“查看详情”中查看。': ('Failed at: {phase}\n{value1}\nReturn to settings, correct the issue, and retry. Full diagnostics are available in View Details.', '失敗した段階：{phase}\n{value1}\n設定に戻って修正し、再試行してください。「詳細を表示」で診断情報を確認できます。'),
    '正在安装高级字幕渲染环境…': ('Installing the advanced subtitle renderer…', '高度な字幕レンダラーをインストール中…'),
    '导出已取消，未生成可交付文件。': ('Export cancelled. No deliverable file was created.', '書き出しをキャンセルしました。完成ファイルは生成されていません。'),
    '至少选择一种字幕格式': ('Select at least one subtitle format', '字幕形式を1つ以上選択してください'),
    '上次保存目录不存在或不可写，已回退到工程导出目录。': ("The previous folder is missing or not writable. Using the project's export folder.", '前回のフォルダーが存在しないか書き込みできないため、プロジェクトの書き出し先を使用します。'),
    '只能删除自定义预设': ('Only custom presets can be deleted', '削除できるのはカスタムプリセットのみです'),
    '{value0} / {value1}  ·  {fps_text} FPS  ·  ETA {value3}\nframe {value4}  ·  速度 {speed_text}  ·  输出 {size}': ('{value0} / {value1} · {fps_text} FPS · ETA {value3}\nFrame {value4} · Speed {speed_text} · Output {size}', '{value0} / {value1} · {fps_text} FPS · 残り {value3}\nフレーム {value4} · 速度 {speed_text} · 出力 {size}'),
    '已加入队列：{value0}': ('Queued: {value0}', 'キューに追加：{value0}'),
    '找不到成片文件，可能已被移动或删除。': ('The encoded video was not found. It may have been moved or deleted.', '書き出した動画が見つかりません。移動または削除された可能性があります。'),
    '无法启动默认播放器，请在文件夹中打开成片。': ('Could not launch the default player. Open the video from its folder.', '既定のプレイヤーを起動できません。フォルダーから動画を開いてください。'),
    '正在取消导出…': ('Cancelling export…', '書き出しをキャンセル中…'),
    '字幕导出失败：{value0}': ('Subtitle export failed: {value0}', '字幕の書き出しに失敗しました：{value0}'),
    '当前 FFmpeg / GPU 不支持': ('Not supported by the current FFmpeg / GPU', '現在の FFmpeg / GPU は対応していません'),
    '无法打开资源管理器；可复制输出位置后手动打开。': ('Could not open File Explorer. Copy the output location and open it manually.', 'エクスプローラーを開けません。出力先をコピーして手動で開いてください。'),
    '上次编码器当前不可用，已回退到自动选择。': ('The previous encoder is unavailable. Switched to automatic selection.', '前回のエンコーダーを利用できないため、自動選択に切り替えました。'),
    '删除选中的渐变色标（Delete / Backspace 也可），至少保留 2 个': ('Delete selected gradient stop (also Delete / Backspace). At least two stops must remain.', '選択したグラデーションの色を削除（Delete / Backspace も使用可）。2色以上残す必要があります。'),
    '搜索字体…': ('Search fonts…', 'フォントを検索…'),
    '立即刷新预览（输入时会自动搜索）': ('Refresh preview now (search updates as you type)', 'プレビューを今すぐ更新（入力中も自動検索）'),
    '要查找的文字，例如：尼奈': ('Text to find, e.g. a misspelled name', '検索する文字（例：誤記された名前）'),
    '替换为，例如：她': ('Replacement text', '置換後の文字'),
    '匹配 {value0} 条字幕 · {value1} 处': ('{value0} subtitles matched · {value1} occurrences', '一致する字幕 {value0} 件 · {value1} 箇所'),
    '正在调用已配置的 AI…': ('Calling the configured AI…', '設定済みの AI にリクエスト中…'),
    '找到 {value0} 处': ('Occurrences found: {value0}', '一致：{value0} 箇所'),
    '输入查找文字后显示匹配数量': ('Enter search text to see the match count', '検索する文字を入力すると一致数を表示します'),
    '没有匹配的字幕': ('No matching subtitles', '一致する字幕はありません'),
    '没有可应用的预览': ('No preview available to apply', '適用できるプレビューはありません'),
    '请使用「生成 AI 预览」': ('Use Generate AI Preview', '「AI プレビューを生成」を使用してください'),
    'AI 清理无法调用：{exc}': ('AI cleanup unavailable: {exc}', 'AI 整理を利用できません：{exc}'),
    '建议剪辑范围（包含铺垫、爆点与收尾）': ('Suggested clip range (setup, highlight, and ending)', '推奨クリップ範囲（前振り・見せ場・締めを含む）'),
    '统计为候选范围簇级口径：有效条数已剔除广告/例行弹幕；峰值=簇内最高倍数窗；惊叹/笑声为弹幕条数（非命中次数）。': ('Statistics refer to candidate clusters. Valid comments exclude ads and routine messages. Peak is the highest multiplier window in the cluster; exclamations and laughter count comments, not word matches.', '統計は候補範囲のまとまり単位です。有効コメント数は広告や定型文を除外し、ピークは範囲内で最大倍率の区間を示します。驚き・笑いは単語の一致数ではなくコメント数です。'),
    '分析设置': ('Analysis Settings', '分析設定'),
    '调整停顿时长与保护量': ('Adjust pause duration and padding', '無音時間と前後の保護幅を調整'),
    '没有检测到人声的连续停顿至少达到此时长才成为候选': ('A continuous interval without detected speech must reach this duration to become a candidate', '人の声が検出されない状態がこの長さ以上続いた箇所を候補にします'),
    '检测完成，尚未应用：{value0} 处候选，已勾选 {value1} 处；预计删除剪辑区间 {value2:.2f} 秒，应用后时间轴 {value3:.2f} 秒。': ('Detection finished, not applied: {value0} candidates, {value1} selected. Estimated removal {value2:.2f} s; resulting timeline {value3:.2f} s.', '検出完了・未適用：候補 {value0} 箇所、選択 {value1} 箇所。削除予定 {value2:.2f} 秒、適用後のタイムライン {value3:.2f} 秒。'),
    '字幕：{cue_count} 条（当前工程）': ('Subtitles: {cue_count} (current project)', '字幕：{cue_count} 件（現在のプロジェクト）'),
    '自动分析：{automatic}（{xml_text}）': ('Automatic analysis: {automatic} ({xml_text})', '自動分析：{automatic}（{xml_text}）'),
    '{automatic} · {value1} 个 · {value2}–{value3} 秒': ('{automatic} · {value1} clips · {value2}–{value3} s', '{automatic} · {value1} 本 · {value2}–{value3} 秒'),
    '剪辑候选箱  {value0}': ('Clip Candidates  {value0}', 'クリップ候補  {value0}'),
    '剪辑候选 · {value0} 条（按推荐度排序）': ('Clip candidates · {value0} (ranked by recommendation)', 'クリップ候補 · {value0} 件（おすすめ順）'),
    '核心 {value0} · 建议保留 {value1}': ('Core {value0} · Suggested range {value1}', '中心 {value0} · 推奨範囲 {value1}'),
    '发现本地切片规则；是否采用以切片分析结果为准。口播停顿使用本地音频检测。': ('Local clipping rules found; actual use depends on analysis results. Speech pauses use local audio detection.', 'ローカルの切り抜きルールを検出しました。使用の有無は分析結果で確認できます。発話の間はローカル音声検出で分析します。'),
    '切片分析使用内置规则；口播停顿使用本地音频检测。': ('Clip analysis uses built-in rules; speech pauses use local audio detection.', '切り抜き分析は内蔵ルールを、発話の間の検出はローカル音声分析を使用します。'),
    '空白工程。先导入视频或音频，再导入弹幕 XML 或字幕。': ('Empty project. Import video or audio first, then comment XML or subtitles.', '空のプロジェクトです。動画または音声を読み込んでから、コメント XML や字幕を追加してください。'),
    '候选数 {value0}\n建议长度 {value1}–{value2}秒': ('Candidates: {value0}\nSuggested duration: {value1}–{value2} s', '候補数：{value0}\n推奨の長さ：{value1}–{value2} 秒'),
    '弹幕 XML\n{prefix}\n{value1}': ('Comment XML\n{prefix}\n{value1}', 'コメント XML\n{prefix}\n{value1}'),
    '更换': ('Change', '変更'),
    '请先识别字幕或导入弹幕 XML': ('Recognize subtitles or import comment XML first', '先に字幕を認識するか、コメント XML を読み込んでください'),
    '当前没有可分析的字幕': ('No subtitles available for analysis', '分析できる字幕はありません'),
    '发现 {value0} 个可能的弹幕 XML': ('Possible comment XML files found: {value0}', 'コメント XML の候補が {value0} 件見つかりました'),
    '选择…': ('Choose…', '選択…'),
    '{count} 条字幕 · {value1} · {media_name}': ('Subtitles: {count} · {value1} · {media_name}', '字幕 {count} 件 · {value1} · {media_name}'),
    '{name}\n{value1}\n{path}\n点击任意位置继续编辑': ('{name}\n{value1}\n{path}\nClick anywhere to continue editing', '{name}\n{value1}\n{path}\nクリックして編集を続ける'),
    '继续编辑该工程': ('Continue editing this project', 'このプロジェクトの編集を続ける'),
    '更多操作': ('More Actions', 'その他の操作'),
    '{count} 条字幕 · {value1} · {progress_text}': ('Subtitles: {count} · {value1} · {progress_text}', '字幕 {count} 件 · {value1} · {progress_text}'),
    '工程详情': ('Project Details', 'プロジェクトの詳細'),
    '正在打开…': ('Opening…', '開いています…'),
    '正在打开工程…': ('Opening project…', 'プロジェクトを開いています…'),
    '已选 {count} 项': ('Selected: {count}', '選択済み：{count} 件'),
    '工程文件已移动': ('Project file missing', 'プロジェクトファイルが見つかりません'),
    '找不到工程文件：\n{project_path}\n\n可以重新定位工程，或从最近记录移除。': ('Project file not found:\n{project_path}\n\nLocate the project or remove it from recent projects.', 'プロジェクトファイルが見つかりません：\n{project_path}\n\n保存先を指定し直すか、最近使ったプロジェクトから削除してください。'),
    '素材检查已结束': ('Media check finished', 'メディアの確認が完了しました'),
    '取消检查': ('Cancel Check', '確認をキャンセル'),
    '正在检查所选素材…': ('Checking selected media…', '選択したメディアを確認中…'),
    '素材已重新链接 · 可撤销': ('Media relinked · Undo available', 'メディアを再リンクしました · 元に戻せます'),
    '该素材已不在当前工程中，请重新选择': ('This media is no longer in the project. Select it again.', 'このメディアは現在のプロジェクトにありません。選択し直してください。'),
    '重新链接失败': ('Relink Failed', '再リンクに失敗しました'),
    '{value0} 个素材脱机 · {detail}': ('{value0} media items offline · {detail}', 'メディア {value0} 件がオフライン · {detail}'),
    '正在读取媒体信息…': ('Reading media information…', 'メディア情報を読み込み中…'),
    '素材已加入时间线': ('Media added to timeline', 'メディアをタイムラインに追加しました'),
    '媒体可用 · 元数据 {value0:.0f} ms': ('Media ready · Metadata {value0:.0f} ms', 'メディア準備完了 · メタデータ {value0:.0f} ms'),
    '媒体 · {value0}': ('Media · {value0}', 'メディア · {value0}'),
    '默认只组织为统一字幕轨，不代表已确认同一个人。原标签保留；旧版本自动分轨设置不沿用。其余方式需要在这里明确选择。': ('The default keeps one subtitle track; it does not confirm that all speech is from one person. Original labels are preserved. Older automatic track-splitting settings are not reused. Select other methods explicitly here.', '既定では字幕を1つのトラックにまとめますが、同一人物と確認したことにはなりません。元のラベルは保持され、旧バージョンの自動トラック分割設定は引き継ぎません。他の方法はここで明示的に選択してください。'),
    '仍使用所选主转写与时间轴模型；需选择本地模型。说话人按上方选择运行，身份需试听确认。': ('Uses the selected transcription and timing models; choose local models. Speaker analysis follows the selection above. Listen to confirm identities.', '選択した書き起こし・時刻調整モデルを使用します。ローカルモデルを選択してください。話者分析は上の選択に従います。声を聞いて人物を確認してください。'),
    '无法读取媒体': ('Cannot Read Media', 'メディアを読み込めません'),
    '打开与主页相同的模型选择弹窗（本地模型下载、在线 API 服务与配置）': ('Open the same model picker as Home (local model downloads and online API configuration)', 'ホームと同じモデル選択画面を開く（ローカルモデルのダウンロード、オンライン API の設定）'),
    '识别时启用词库：{display_name}': ('Use term library during recognition: {display_name}', '認識で用語集を使用：{display_name}'),
    '波形不可用': ('Waveform unavailable', '波形を利用できません'),
    '媒体预览加载失败': ('Media preview failed to load', 'メディアのプレビューを読み込めませんでした'),
    '未选择词库': ('No term library selected', '用語集が未選択です'),
    '仅本地识别需要本地主转写、时间轴及说话人方案，请展开高级配置。': ('Local-only recognition requires local transcription, timing, and speaker models. Expand advanced configuration.', 'ローカルのみで認識するには、書き起こし・時刻調整・話者分析のローカルモデルが必要です。詳細設定を開いてください。'),
    '{value0} 个素材': ('Media items: {value0}', 'メディア {value0} 件'),
    '0 个素材': ('No media', 'メディアなし'),
    '把当前 Inspector 中的动效（时长 / 缓动 / 延迟 / 参数）保存为可复用 Motion': ('Save the current Inspector animation (duration, easing, delay, and parameters) as a reusable Motion', '現在のインスペクターのアニメーション（長さ・イージング・遅延・各パラメーター）を再利用可能な Motion として保存'),
    '搜索动效': ('Search animations', 'アニメーションを検索'),
    '重命名 Motion': ('Rename Motion', 'Motion の名前を変更'),
    '可选描述': ('Optional description', '説明（任意）'),
    '保存当前 Motion': ('Save Current Motion', '現在の Motion を保存'),
    'Motion 名称（必填）': ('Motion name (required)', 'Motion 名（必須）'),
    '来源：{entrance_type} · 入场 {value1}ms': ('Source: {entrance_type} · Entrance {value1}ms', '元の動き：{entrance_type} · 入場 {value1}ms'),
    '重命名自建 Motion': ('Rename Custom Motion', 'カスタム Motion の名前を変更'),
    '删除自建 Motion': ('Delete Custom Motion', 'カスタム Motion を削除'),
    '播放性能 · Ctrl+Shift+P': ('Playback Performance · Ctrl+Shift+P', '再生パフォーマンス · Ctrl+Shift+P'),
    '{state}  ·  {value1:g}×  ·  {value2} 个解码器\n发布 {value3} fps    合成 P95 {value4} ms    发布 P95 {value5} ms': ('{state} · {value1:g}× · {value2} decoders\nDelivery {value3} fps    Compositing P95 {value4} ms    Delivery P95 {value5} ms', '{state} · {value1:g}× · デコーダー {value2}\n配信 {value3} fps    合成 P95 {value4} ms    配信 P95 {value5} ms'),
    '已复制诊断数据': ('Diagnostic data copied', '診断データをコピーしました'),
    '发现未保存的自动恢复版本': ('Unsaved Recovery Version Found', '未保存の復元データが見つかりました'),
    '自动恢复包含正式保存之后的实际修改。': ('The recovery version contains changes made after the last manual save.', '復元データには、最後の手動保存以降の変更が含まれています。'),
    '压制前请安装字体或在样式中选择已安装字体。': ('Install the font or select an installed font in Styles before encoding.', 'エンコード前にフォントをインストールするか、スタイルでインストール済みのフォントを選択してください。'),
    '已收口{value0}条说话人交接显示边界，可撤销；原始声学证据保留。': ('Adjusted {value0} speaker handoff display boundaries. Undo is available; original acoustic evidence was preserved.', '話者交代時の表示境界を {value0} 箇所調整しました。元に戻せます。元の音響情報は保持しています。'),
    '{stage}失败\n{error}\n工程文件仍保留，可重试载入：\n{value2}': ('{stage} failed\n{error}\nThe project file was kept. Retry loading:\n{value2}', '{stage}に失敗しました\n{error}\nプロジェクトファイルは保持されています。再読み込みできます：\n{value2}'),
    '默认保存到全局设置；例如 _字幕版': ('Saved as a global default; e.g. _subtitled', '全体の既定値として保存（例：_字幕付き）'),
    '正在检测可用编码器（后台运行，不阻塞窗口）…': ('Detecting available encoders in the background…', '利用可能なエンコーダーをバックグラウンドで検出中…'),
    '正在压制...': ('Encoding…', 'エンコード中…'),
    '已加入压制队列: {value0}': ('Added to encoding queue: {value0}', 'エンコードキューに追加：{value0}'),
    '视频已保存：\n{output}': ('Video saved:\n{output}', '動画を保存しました：\n{output}'),
    '正在压制 0%': ('Encoding 0%', 'エンコード中 0%'),
    '编码器：{value0}': ('Encoder: {value0}', 'エンコーダー：{value0}'),
    '未能检测可用编码器，请检查 FFmpeg 运行时': ('No available encoders detected. Check the FFmpeg runtime.', '利用可能なエンコーダーを検出できません。FFmpeg の実行環境を確認してください。'),
    '正在压制 {percent}% · {time_value}': ('Encoding {percent}% · {time_value}', 'エンコード中 {percent}% · {time_value}'),
    '✓ 已确认 · 下一条优先字幕': ('✓ Confirmed · Next priority subtitle', '✓ 確認済み · 次の優先字幕へ'),
    '已切换 · 正在定位': ('Switched · Seeking', '切り替えました · 移動中'),
    '✓ 已采用 {label}': ('✓ Applied {label}', '✓ {label} を採用しました'),
    '✓ 文本一致 · 仅断句差异': ('✓ Same text · Different segmentation only', '✓ 文字は一致 · 区切り方のみ異なります'),
    '✓ 已采用候选 {value0} · 下一条': ('✓ Applied candidate {value0} · Next', '✓ 候補 {value0} を採用 · 次へ'),
    '说话人候选不同': ('Speaker candidates differ', '話者の候補が異なります'),
    '文本一致：{value0}<br>说话人候选：{value1}': ('Matching text: {value0}<br>Speaker candidates: {value1}', '一致する文字：{value0}<br>話者候補：{value1}'),
    '审核完成  {value0} / {value1}': ('Review complete  {value0} / {value1}', '確認完了  {value0} / {value1}'),
    '⚠ 候选文本存在差异': ('⚠ Candidate texts differ', '⚠ 候補の文字が異なります'),
    'Studio 快捷键': ('Studio Shortcuts', 'Studio のショートカット'),
    '搜索命令': ('Search commands', 'コマンドを検索'),
    '筛选名称或标签': ('Filter by name or label', '名前またはラベルで絞り込み'),
    '跳到该说话人最长的一条字幕并播放': ("Jump to this speaker's longest subtitle and play", 'この話者の最も長い字幕に移動して再生'),
    '人工指定主讲说话人（不做自动身份推断）': ('Manually select the main speaker (no automatic identity inference)', '主な話者を手動で指定（人物を自動推定しません）'),
    '隐藏其它全部说话人（成片与导出不再包含；可撤销）': ('Hide all other speakers (excluded from video and subtitle export; undo available)', '他の話者をすべて非表示にする（動画・字幕の書き出しから除外。元に戻せます）'),
    '打开当前工程识别设置，可选 Nemotron。会重新生成字幕，不是只补标签；请先保存人工编辑的工程副本。': ('Open recognition settings for this project, including Nemotron. This regenerates subtitles, not just labels. Save a copy of your edited project first.', '現在のプロジェクトの認識設定を開きます。Nemotron も選択できます。ラベルだけでなく字幕全体を再生成するため、先に編集済みプロジェクトのコピーを保存してください。'),
    '正在应用…': ('Applying…', '適用中…'),
    '正在从本地缓存恢复已选说话人并刷新当前工程…': ('Restoring selected speakers from local cache and updating the project…', '選択した話者をローカルキャッシュから復元し、プロジェクトを更新中…'),
    '已选 {value0} 人 / {count} 条字幕': ('Speakers selected: {value0} / Subtitles: {count}', '選択した話者 {value0} 人 / 字幕 {count} 件'),
    '选择说话人颜色': ('Choose Speaker Color', '話者の色を選択'),
    '请先等待媒体预览就绪，再点击试听。': ('Wait for the media preview to be ready before listening.', 'メディアのプレビュー準備が完了してから試聴してください。'),
    '应用成功：当前工程已更新为 {value0} 条主要说话人字幕轨 / {value1} cue。新增原文及时间待复核；可撤销、保存和重开。': ('Applied: the project now has {value0} main-speaker subtitle tracks / {value1} cues. Review the added text and timing. Undo, save, and reopen are available.', '適用しました。主な話者の字幕トラック {value0} 本 / 字幕 {value1} 件に更新されています。追加された文字と時刻を確認してください。元に戻す・保存・再読み込みが可能です。'),
    '应用选择并从缓存重建轨道': ('Apply Selection and Rebuild Tracks from Cache', '選択を適用し、キャッシュからトラックを再構成'),
    '内部身份：{value0}': ('Internal identity: {value0}', '内部 ID：{value0}'),
    '没有完整任务的原始发言统计，保留当前整理。': ('Full-task speech statistics are unavailable. Keeping the current organization.', 'タスク全体の元の発話統計がないため、現在の整理結果を維持します。'),
    '应用失败，当前工程已保留原状态：{value0}: {exc}': ('Apply failed; the project was left unchanged: {value0}: {exc}', '適用に失敗しました。プロジェクトは元の状態を保持しています：{value0}: {exc}'),
    '仅影响预览。Noita 草稿关闭火星和细纹，标准保留核心炼金层，完整显示全部；采用后后台生成透明缓存，准备好后播放自动使用。文字/样式/时间/位置变化会重新生成，原 HTML 和最终导出保留完整效果。': ('Preview only. Noita Draft hides sparks and fine lines, Standard keeps the core alchemy layers, and Full shows everything. Applying a design prepares a transparent cache for playback. Text, style, timing, or position changes rebuild it. The original HTML and final export keep all effects.', 'プレビューにのみ影響します。Noita の下書きは火花や細線を省略し、標準は主要な錬金術レイヤー、完全はすべてを表示します。採用後、再生用の透明キャッシュを生成します。文字・スタイル・時刻・位置の変更時は再生成し、元の HTML と最終書き出しには全効果を残します。'),
    '对 AI 说：要改什么？\n例如：主色改成枪灰、背景更透明、入场更快': ('Tell AI what to change.\nFor example: gunmetal text, a more transparent background, or a faster entrance.', 'AI に変更内容を伝えてください。\n例：主な色をガンメタルに、背景をより透明に、入場を速く'),
    '启用': ('Enable', '有効にする'),
    '启用或关闭字幕背景框': ('Enable or disable the subtitle background box', '字幕の背景枠を有効・無効にする'),
    '勾选后，批量应用样式时同步应用当前的位置、边距与缩放；关闭则保留每条字幕各自的几何。': ('When checked, bulk style changes also apply the current position, margins, and scale. Otherwise, each subtitle keeps its own geometry.', 'オンにすると、スタイルの一括適用時に現在の位置・余白・拡大率も適用します。オフの場合は各字幕の配置を維持します。'),
    '精确颜色值': ('Exact Color Value', '正確な色の値'),
    '应用已保存的 AI 样式': ('Apply Saved AI Style', '保存済みの AI スタイルを適用'),
    '已恢复普通字幕': ('Standard subtitles restored', '通常の字幕に戻しました'),
    '内置样式不能重命名': ('Built-in styles cannot be renamed', '内蔵スタイルの名前は変更できません'),
    '特效字幕已应用：{name}': ('Subtitle effect applied: {name}', '字幕エフェクトを適用しました：{name}'),
    '⚠ 网页主题无效，未应用：{exc}': ('⚠ Invalid web theme; not applied: {exc}', '⚠ ウェブテーマが無効なため適用しませんでした：{exc}'),
    '⚠ AI 方案图形无效，未应用：{exc}': ('⚠ Invalid AI design graphics; not applied: {exc}', '⚠ AI デザインのグラフィックが無効なため適用しませんでした：{exc}'),
    '高级位置设置': ('Advanced Position Settings', '位置の詳細設定'),
    '搜索预设名称…': ('Search preset names…', 'プリセット名を検索…'),
    '{value0} · Engine: {value1}\n字体 {value2} · {value3}px · 填充 {value4} · 描边 {value5} · 动效 {value6}': ('{value0} · Engine: {value1}\nFont {value2} · {value3}px · Fill {value4} · Outline {value5} · Animation {value6}', '{value0} · エンジン：{value1}\nフォント {value2} · {value3}px · 塗り {value4} · 縁取り {value5} · アニメーション {value6}'),
    '未随包提供 · 当前使用安全回退字体': ('Not bundled · Using a safe fallback font', '同梱されていません · 代替フォントを使用中'),
    '{value0} 个预设': ('Presets: {value0}', 'プリセット {value0} 件'),
    '删除全部 AI 生成': ('Delete All AI Designs', 'AI デザインをすべて削除'),
    '无法生成受支持的样式：{exc}': ('Could not generate a supported style: {exc}', '対応するスタイルを生成できませんでした：{exc}'),
    '再次点击确认删除全部 AI': ('Click again to delete all AI designs', '再度クリックすると AI デザインをすべて削除します'),
    '应用到{label}': ('Apply to {label}', '{label}に適用'),
    '打开颜色选择器': ('Open Color Picker', 'カラーピッカーを開く'),
    '生成三个方向': ('Generate Three Directions', '3つの方向性を生成'),
    '检查视觉审核结果': ('Review Visual Results', 'ビジュアルの確認結果を見る'),
    '继续修复已保存的三稿': ('Continue Repairing the Three Saved Drafts', '保存済みの3案の修復を続ける'),
    '拖动调整{value0}高度 · 双击恢复默认': ('Drag to resize {value0} · Double-click to reset', 'ドラッグで {value0} の高さを変更 · ダブルクリックでリセット'),
    '按住上下拖动调整轨道层级（上层画面覆盖下层）；拖片段到另一条轨也能交换': ('Drag vertically to reorder tracks (upper video covers lower video). Drag a clip to another track to swap.', '上下にドラッグしてトラックの順序を変更（上の映像が下を覆います）。クリップを他のトラックへドラッグして入れ替えることもできます。'),
    '显示或隐藏该说话人轨道': ('Show or hide this speaker track', 'この話者トラックを表示・非表示'),
    '{value0} · {audio_track_id} 波形': ('{value0} · {audio_track_id} Waveform', '{value0} · {audio_track_id} 波形'),
    '锁定或解锁该说话人轨道': ('Lock or unlock this speaker track', 'この話者トラックをロック・解除'),
    '删除字幕轨道（可撤销，不删除文件）': ('Delete subtitle track (undo available; files are kept)', '字幕トラックを削除（元に戻せます。ファイルは削除しません）'),
    '轨道音量': ('Track Volume', 'トラックの音量'),
    '重置为 0 dB': ('Reset to 0 dB', '0 dB にリセット'),
    '请先选择要调整音量的 A 波形行；该视频没有关联音频轨': ('Select an audio waveform row first. This video has no linked audio track.', '音量を調整する A 波形の行を選択してください。この動画には関連する音声トラックがありません。'),
    '音轨或关联视频轨已锁定，请先解锁': ('The audio or linked video track is locked. Unlock it first.', '音声または関連する動画トラックがロックされています。先に解除してください。'),
    'AI 字幕翻译（双语对照）': ('AI Subtitle Translation (Bilingual)', 'AI 字幕翻訳（対訳表示）'),
    '恢复快照已安全写入磁盘；正式工程仍保留未保存修改。': ('Recovery snapshot safely saved. The project still has unsaved edits.', '復元用スナップショットを安全に保存しました。プロジェクトには未保存の編集が残っています。'),
    '建议已忽略': ('Suggestion dismissed', '提案を無視しました'),
    '说话人：{value0}': ('Speaker: {value0}', '話者：{value0}'),
    '字幕：{value0}  /  {value1}': ('Subtitles: {value0} / {value1}', '字幕：{value0} / {value1}'),
    '样式：{value0}  ·  动效：{value1}': ('Style: {value0} · Animation: {value1}', 'スタイル：{value0} · アニメーション：{value1}'),
    '时间线为空': ('Timeline is empty', 'タイムラインは空です'),
    '已清除旧画面、字幕和播放状态；按 Ctrl+Z 可恢复': ('Previous video, subtitles, and playback state cleared. Press Ctrl+Z to restore.', '前の映像・字幕・再生状態を消去しました。Ctrl+Z で復元できます。'),
    '时间码格式：mm:ss.ms 或 hh:mm:ss.ms': ('Timecode: mm:ss.ms or hh:mm:ss.ms', 'タイムコード：mm:ss.ms または hh:mm:ss.ms'),
    '自动保存失败: {message}': ('Autosave failed: {message}', '自動保存に失敗しました：{message}'),
    '纯音频工程': ('Audio-only Project', '音声のみのプロジェクト'),
    '{value0} · 音频波形与字幕预览 · 当前时间随 ProjectClock 更新': ('{value0} · Audio waveform and subtitle preview · Time follows ProjectClock', '{value0} · 音声波形と字幕のプレビュー · 時刻は ProjectClock に同期'),
    '关闭前自动保存失败: {exc}': ('Autosave before closing failed: {exc}', '終了前の自動保存に失敗しました：{exc}'),
    '保存失败：{exc}': ('Save failed: {exc}', '保存に失敗しました：{exc}'),
    '音频准备超时，请重试播放或检查素材。': ('Audio preparation timed out. Try playing again or check the media.', '音声の準備がタイムアウトしました。再生を再試行するか、メディアを確認してください。'),
    '正在试听：原剪口两侧 → 短间隔 → 压缩后剪口。时间轴未应用。再次检测或切换工程会停止试听。': ('Listening: both sides of the original cut → short gap → shortened cut. Not applied to the timeline. Detecting again or switching projects stops playback.', '試聴中：元の切断点の前後 → 短い間隔 → 短縮後の切断点。タイムラインには未適用です。再検出やプロジェクト切り替えで試聴を停止します。'),
    '播放头不在视频片段内部，未分割': ('Playhead is outside a video clip; nothing was split', '再生ヘッドが動画クリップの外にあるため分割しませんでした'),
    '已闭合 {value0} 空白及关联音频（其他轨道保持原位）': ('Closed the {value0} gap and linked audio (other tracks stayed in place)', '{value0} の空白と関連音声を詰めました（他のトラックは位置を維持）'),
    '检测已过期，请重新检测后试听。': ('Detection is outdated. Detect again before listening.', '検出結果が古くなっています。再検出してから試聴してください。'),
    '已交换 {source_track_id}/{target_track_id} 层级（可撤销）': ('Swapped {source_track_id}/{target_track_id} layer order (undo available)', '{source_track_id}/{target_track_id} の重ね順を入れ替えました（元に戻せます）'),
    '上移未完成：主轨已锁定': ('Cannot move up: main track is locked', '上に移動できません：メイントラックがロックされています'),
    '上移未完成：该段素材不在媒体池': ('Cannot move up: clip media is not in the media pool', '上に移動できません：クリップのメディアがメディアプールにありません'),
    '{value0} 轨道已锁定，请先解锁': ('Track {value0} is locked. Unlock it first.', 'トラック {value0} はロックされています。先に解除してください。'),
    '当前声音：{value0} · {state} · 单一引擎 · {value2}': ('Audio: {value0} · {state} · Single engine · {value2}', '音声：{value0} · {state} · 単一エンジン · {value2}'),
    '试听不可用：{exc}': ('Listening unavailable: {exc}', '試聴できません：{exc}'),
    '换轨未完成：{exc}': ('Track move failed: {exc}', 'トラックの移動に失敗しました：{exc}'),
    '上移未完成：{exc}': ('Move up failed: {exc}', '上への移動に失敗しました：{exc}'),
    '预览：{value0} {value1} · 多轨合成 · 当前声音 {master_id}': ('Preview: {value0} {value1} · Multitrack composite · Audio {master_id}', 'プレビュー：{value0} {value1} · マルチトラック合成 · 音声 {master_id}'),
    '当前声音：{names} · 混音 · {value1}': ('Audio: {names} · Mix · {value1}', '音声：{names} · ミックス · {value1}'),
    '当前声音：所有可用、未静音音轨混音': ('Audio: mix all available, unmuted tracks', '音声：利用可能でミュートされていない全トラックをミックス'),
    '旧工程指定声音：{value0}（兼容保留）；选择全轨混音可取消，S独听优先。': ('Legacy project audio: {value0} (kept for compatibility). Select All-track Mix to clear this; S solo takes priority.', '旧プロジェクトの指定音声：{value0}（互換性のため維持）。全トラックのミックスを選ぶと解除できます。S のソロが優先されます。'),
    '预览：当前位置没有可用的启用片段': ('Preview: no available enabled clip at this position', 'プレビュー：この位置には有効で利用可能なクリップがありません'),
    '特效字幕库 · Web 主题': ('Subtitle Effect Library · Web Themes', '字幕エフェクトライブラリ · ウェブテーマ'),
    '预览不可用': ('Preview unavailable', 'プレビューを利用できません'),
    'AI 字幕工坊 · 对话式精修': ('AI Subtitle Workshop · Refine by Chat', 'AI 字幕工房 · 対話で調整'),
    '对 AI 说修改要求，例如：框换成血红色、字带金属拉丝、粒子更多……': ('Describe changes to AI, e.g. a crimson border, brushed-metal text, or more particles…', 'AI に変更内容を入力（例：枠を深紅に、文字をヘアライン金属風に、粒子を増やす）…'),
    '加载动画…': ('Loading animation…', 'アニメーションを読み込み中…'),
    'AI 修改中…': ('AI is refining…', 'AI が調整中…'),
    '正在请求 AI…': ('Requesting AI…', 'AI にリクエスト中…'),
    '发送给 AI': ('Send to AI', 'AI に送信'),
    '当前请求仍在进行，请稍后修改': ('A request is still running. Wait before making more changes.', 'リクエストを実行中です。完了してから次の変更を行ってください。'),
    '动画加载超时，可关闭后重试；原主题保留': ('Animation loading timed out. Close and retry; the original theme was kept.', 'アニメーションの読み込みがタイムアウトしました。閉じて再試行してください。元のテーマは保持されています。'),
    '此请求已被替换': ('This request was replaced', 'このリクエストは新しいものに置き換えられました'),
    '选中时间轴上的字幕后，在这里直接改文字': ('Select a subtitle on the timeline, then edit its text here', 'タイムラインの字幕を選択すると、ここで文字を編集できます'),
    '单语显示模式': ('Single-language Display', '単一言語表示'),
    '双语显示模式': ('Bilingual Display', '対訳表示'),
    '当前字幕文本': ('Current Subtitle Text', '現在の字幕テキスト'),
    '第二语言文本': ('Second-language Text', '翻訳テキスト'),
    '保持说话时间不变，把发生空间遮挡的字幕稳定上移；手动固定位置优先': ('Keep speech timing and move overlapping subtitles upward. Manually fixed positions take priority.', '発話時刻を維持し、重なった字幕を上に移動します。手動で固定した位置を優先します。'),
    '启动最多 120 秒本应用状态诊断；再次点击标记异常，不录音': ('Start an application-state diagnostic for up to 120 seconds. Click again to mark an issue. No audio is recorded.', '最大120秒間のアプリ状態診断を開始します。再クリックで問題の発生時点を記録します。録音は行いません。'),
    '开启时连续跟随；关闭时仅越界翻页，播放头左对齐。字幕选择保持不变。': ('When on, follow continuously. When off, page only at the edge with the playhead aligned left. Subtitle selection is unchanged.', 'オンでは連続して追従します。オフでは表示範囲を越えたときだけ再生ヘッドを左端に揃えてページを切り替えます。字幕の選択は変わりません。'),
    '输入主题即可，例如：初音未来风格 / Minecraft像素风格。\n也可以补充构图、色彩、动作或参考；系统会展开成完整作品。': ('Enter a theme, e.g. Hatsune Miku or Minecraft pixel art.\nOptionally add composition, colors, motion, or references; the system develops a complete design.', 'テーマを入力してください（例：初音ミク風、Minecraft のピクセルアート風）。\n構図、色、動き、参考資料も指定できます。システムが完成形のデザインに展開します。'),
    '草案来自可运行定义，可直接采用；后续只按明确选择增补。3个完整候选会增加模型调用与费用。': ('Drafts use runnable definitions and can be applied directly. Further work follows your explicit choices. Three complete options require more model calls and cost.', '下書きは実行可能な定義から作成され、そのまま採用できます。追加作業は明示した選択に従います。完成候補を3つ作る場合、モデル呼び出しと費用が増えます。'),
    '生成后，这里会显示视觉设计配方，不会修改字幕文本。': ('The visual design recipe will appear here after generation. Subtitle text will not be changed.', '生成後、ここにビジュアルデザインの設定を表示します。字幕テキストは変更しません。'),
    'AI 输出流（HTML/CSS 代码将实时显示在这里）': ('AI output stream (HTML/CSS appears here as it arrives)', 'AI の出力（HTML/CSS を受信しながら表示）'),
    '导出为独立档案（theme.html 双击即可播放动画演示 + theme.json）': ('Export a standalone archive (double-click theme.html to play the animation demo, plus theme.json)', '独立したアーカイブとして書き出し（theme.html をダブルクリックするとアニメーションを再生。theme.json も含む）'),
    '从 .2byte-theme 档案（theme.html/theme.json）载入主题': ('Load a theme from a .2byte-theme archive (theme.html/theme.json)', '.2byte-theme アーカイブ（theme.html/theme.json）からテーマを読み込む'),
    '分镜 {value0}': ('Storyboard {value0}', '絵コンテ {value0}'),
    '从预设库隐藏，不会删除安装包资源': ('Hide from the preset library; bundled resources are kept', 'プリセット一覧から非表示にする。同梱リソースは削除しません'),
    '字幕本体 · {seconds:g} 秒循环 · 中性底；全程保持统一放大比例': ('Subtitle only · {seconds:g}-second loop · Neutral background; constant zoom throughout', '字幕のみ · {seconds:g} 秒ループ · 無地の背景・一定の拡大率'),
    '点击暂停 / 继续循环': ('Click to pause or resume the loop', 'クリックでループを一時停止・再開'),
    '字幕候选作品工作台': ('Subtitle Design Candidates', '字幕デザインの候補'),
    '点击播放 / 暂停；就绪后自动循环': ('Click to play/pause; loops automatically when ready', 'クリックで再生・一時停止。準備完了後に自動ループ'),
    '画面占比': ('Frame Coverage', '画面内の大きさ'),
    '切换字幕本体 / 完整画面': ('Switch between subtitle-only and full-frame view', '字幕のみ・画面全体を切り替え'),
    '放大': ('Zoom In', '拡大'),
    '展开设计与过程': ('Expand Design and Activity', 'デザインと処理過程を展開'),
    '停止并保留': ('Stop and Keep', '停止して保持'),
    '本地精修文字': ('Refine Text Locally', '文字をローカルで調整'),
    '校验并应用精修': ('Validate and Apply Refinement', '調整内容を検証して適用'),
    '选择本地视频或音频': ('Choose Local Video or Audio', 'ローカルの動画・音声を選択'),
    '清除已保存的 API Key': ('Clear Saved API Key', '保存済み API キーを削除'),
    '将在保存时清除已保存的密钥（环境变量不受影响）': ('The saved key will be cleared when you save (environment variables are unchanged)', '保存時に保存済みキーを削除します（環境変数は変更しません）'),
    '已请求清除：点击“保存 AI 配置”生效': ('Clear requested: click Save AI Config to apply', '削除を予約しました。「AI 設定を保存」で適用します'),
    '正在后台获取模型列表…': ('Fetching model list in the background…', 'モデル一覧をバックグラウンドで取得中…'),
    '正在取消模型发现…': ('Cancelling model discovery…', 'モデルの検出をキャンセル中…'),
    'CLI：检测中…': ('CLI: checking…', 'CLI：確認中…'),
    '2ByteASR 品牌标志': ('2ByteASR brand logo', '2ByteASR のロゴ'),
    '当前版本 {value0} · 检查 GitHub Release': ('Version {value0} · Check GitHub Releases', '現在のバージョン {value0} · GitHub Releases を確認'),
    '正在载入 Studio': ('Loading Studio', 'Studio を読み込み中'),
    '教学提示已重置；下次进入相应功能时会再次显示。': ('Tutorial hints reset. They will appear again when you next use each feature.', '操作ガイドをリセットしました。次回各機能を開いたときに再表示します。'),
    '已载入 {value0}；请填写该服务的 API Key 后保存': ("Loaded {value0}. Enter the service's API key and save.", '{value0} を読み込みました。このサービスの API キーを入力して保存してください。'),
    '转写风格：清爽=模型与本地成片规则都会去掉语气词；逐字=按原话保留（含口误），孤立语气词不再省略。': ('Transcription style: Clean removes fillers through model and local rules; Verbatim preserves original speech, including slips and isolated fillers.', '書き起こしスタイル：「読みやすく」はモデルとローカルルールでフィラーを削除します。「逐語」は言い間違いや単独のフィラーも含めて発話を保持します。'),
    '只影响之后生成的字幕；不改已编辑的工程。数字只换写法，不求和或去重。': ('Affects newly generated subtitles only, not edited projects. Numbers change notation only; they are not summed or deduplicated.', '今後生成する字幕にのみ影響し、編集済みのプロジェクトは変更しません。数字は表記のみを変更し、合算や重複削除は行いません。'),
    '<b>API 帮助</b> · {label}': ('<b>API Help</b> · {label}', '<b>API ヘルプ</b> · {label}'),
    '已获取 {value0} 个模型；选择后自动填入“API 模型”。如列表不全可手动填写。': ('Models retrieved: {value0}. Selecting one fills API Model. Enter a model manually if it is missing.', 'モデルを {value0} 件取得しました。選択すると「API モデル」に反映します。一覧にない場合は手動で入力できます。'),
    '自动获取失败：{short}；请直接在“API 模型（可手动）”填写。': ('Automatic retrieval failed: {short}. Enter it in API Model (manual input).', '自動取得に失敗しました：{short}。「API モデル（手動入力可）」に直接入力してください。'),
    '关闭在线识别设置': ('Close Online Recognition Settings', 'オンライン認識設定を閉じる'),
    '例如 2byte': ('For example, 2byte', '例：2byte'),
    '尚未保存，请输入 AccessKey ID（RAM 子账号即可）': ('Not saved. Enter AccessKey ID (a RAM sub-account is sufficient).', '未保存です。AccessKey ID を入力してください（RAM サブアカウント可）。'),
    '可自行修改并保存；重新打开或切回该服务时会恢复你保存的地址': ('Edit and save this URL. Your saved URL is restored when reopening or switching back to this service.', 'URL は編集して保存できます。画面を開き直すか、このサービスに戻ると保存した URL を復元します。'),
    '素材 {media_index} / {media_total}  ·  已完成 {finished} / {total_stages} 个阶段': ('Media {media_index} / {media_total} · Stages completed {finished} / {total_stages}', 'メディア {media_index} / {media_total} · 完了した段階 {finished} / {total_stages}'),
    '成功 {success_count} 个 · 失败 {failure_count} 个 · 取消 {cancel_count} 个 · 总耗时 {value3:.1f} 秒': ('Succeeded {success_count} · Failed {failure_count} · Cancelled {cancel_count} · Elapsed {value3:.1f} s', '成功 {success_count} 件 · 失敗 {failure_count} 件 · キャンセル {cancel_count} 件 · 合計 {value3:.1f} 秒'),
    '此前选择的模型 {stored} 已不可用，请从当前可用模型中重新选择；保存新选择后旧值会被移除。': ('Previously selected model {stored} is unavailable. Select an available model; saving replaces the old selection.', '前回選択したモデル {stored} は利用できません。利用可能なモデルを選んで保存すると、古い選択を置き換えます。'),
    '请先检测 CLI 与登录状态': ('Check CLI and sign-in status first', '先に CLI とログイン状態を確認してください'),
    '该服务不支持自动获取模型列表；可直接输入模型 ID': ('This service has no automatic model list. Enter a model ID directly.', 'このサービスはモデル一覧の自動取得に対応していません。モデル ID を直接入力してください。'),
    '已发现 {value0} 个模型 · 当前所选不在最新列表中，请确认后保存': ('Models found: {value0} · Current selection is missing from the latest list; verify before saving', 'モデルを {value0} 件検出 · 現在の選択は最新一覧にありません。確認してから保存してください'),
    '已发现 {value0} 个模型 · 可搜索选择或手动输入': ('Models found: {value0} · Search, select, or enter one manually', 'モデルを {value0} 件検出 · 検索・選択または手動入力できます'),
    '重新登录或切换账号': ('Sign In Again or Switch Account', '再ログイン・アカウント切り替え'),
    '正在取消官方登录…': ('Cancelling official sign-in…', '公式ログインをキャンセル中…'),
    '取消测试': ('Cancel Test', 'テストをキャンセル'),
    '正在执行最小连接测试…': ('Running a minimal connection test…', '最小限の接続テストを実行中…'),
    '模型响应较慢，仍在等待… {elapsed} 秒 · 可取消': ('Model response is slow; still waiting… {elapsed} s · You can cancel', 'モデルの応答を待っています… {elapsed} 秒 · キャンセルできます'),
    '无法打开工程': ('Cannot Open Project', 'プロジェクトを開けません'),
    '字幕已生成，工程载入失败': ('Subtitles generated; project loading failed', '字幕を生成しましたが、プロジェクトの読み込みに失敗しました'),
    '工程文件未找到：{target}；请从结果页打开已保存的字幕': ('Project file not found: {target}. Open the saved subtitles from the results page.', 'プロジェクトファイルが見つかりません：{target}。結果画面から保存済み字幕を開いてください。'),
    '识别完成': ('Recognition Complete', '認識完了'),
    '识别期间你对工程做了编辑。': ('You edited the project while recognition was running.', '認識の実行中にプロジェクトが編集されました。'),
    '下载更新 {percent}%': ('Downloading update {percent}%', '更新をダウンロード中 {percent}%'),
    '已下载 {value0:.1f} MB': ('Downloaded {value0:.1f} MB', 'ダウンロード済み {value0:.1f} MB'),
    'AI 模型配置缺失': ('AI Model Configuration Missing', 'AI モデルの設定がありません'),
    '上次失败与 AI 模型配置有关（示例：{value0}）。\n\n请先在「AI 模型与密钥」中选择厂商并填写 API 密钥，或使用 Grok 账号登陆；完成后再回本页重试失败项。': ('The previous failure involved AI model configuration (example: {value0}).\n\nSelect a provider and enter an API key in AI Models & Keys, or sign in with a Grok account. Then return here to retry failed tasks.', '前回の失敗は AI モデル設定に関連しています（例：{value0}）。\n\n「AI モデルとキー」でプロバイダーと API キーを設定するか、Grok アカウントでログインしてください。その後、この画面で失敗したタスクを再試行できます。'),
    '清空全部': ('Clear All', 'すべてクリア'),
    '移除全部待处理素材': ('Remove all pending media', '待機中のメディアをすべて削除'),
    '当前识别任务正在运行；请完成或取消后切换方案。': ('Recognition is running. Finish or cancel it before switching plans.', '認識を実行中です。完了するかキャンセルしてからプランを切り替えてください。'),
    '方案中的断句模型 {retired_ref} 已不可用；已保留当前全局选择，重新选择并保存后将更新方案。': ('Segmentation model {retired_ref} in this plan is unavailable. The current global selection was kept. Select and save a replacement to update the plan.', 'このプランの分割モデル {retired_ref} は利用できません。現在の全体設定を維持しています。別のモデルを選んで保存するとプランを更新します。'),
    '<b>当前选择</b>：{value0}': ('<b>Current selection</b>: {value0}', '<b>現在の選択</b>：{value0}'),
    '原生接口无模型列表；按官方固定型号调用，实际识别尚需验证。': ('The native API has no model list; it uses the official fixed model. Actual recognition still needs verification.', 'ネイティブ API にモデル一覧はありません。公式の固定モデルを使用します。実際の認識は別途確認が必要です。'),
    '已从缓存载入 {value0} 个模型（最近成功获取）。': ('Loaded {value0} models from the last successful cached list.', '前回正常に取得したキャッシュからモデルを {value0} 件読み込みました。'),
    '已保存（···{value0}；修改后保存即覆盖）': ('Saved (···{value0}; editing and saving replaces it)', '保存済み（···{value0}。編集して保存すると上書き）'),
    '尚未保存，请输入 AccessKey Secret': ('Not saved. Enter AccessKey Secret.', '未保存です。AccessKey Secret を入力してください。'),
    '正在测试连接…': ('Testing connection…', '接続をテスト中…'),
    '正在测试 OSS（上传探针 → 预签名下载 → 删除）…': ('Testing OSS (upload probe → signed download → delete)…', 'OSS をテスト中（試験ファイルのアップロード → 署名付きダウンロード → 削除）…'),
    '当前任务仍使用启动配置；请任务结束后保存转写与对齐设置。': ('The running task keeps its startup configuration. Save transcription and alignment settings after it finishes.', '実行中のタスクは開始時の設定を維持します。完了してから書き起こし・時刻調整の設定を保存してください。'),
    '已添加术语：{value}（可在“术语库与学习记录”中删除）': ('Term added: {value} (remove it in Term Library & Learning History)', '用語を追加しました：{value}（「用語集と学習履歴」で削除できます）'),
    '字幕文件与工程交付状态见结果页': ('See the results page for subtitle files and project delivery status', '字幕ファイルとプロジェクトの出力状況は結果画面で確認できます'),
    '识别子任务已退出': ('Recognition subtask exited', '認識サブタスクが終了しました'),
    '任务已结束 · {value0} 个阶段完成 · {skipped} 个阶段不适用': ('Task finished · {value0} stages completed · {skipped} not applicable', 'タスク終了 · {value0} 段階完了 · {skipped} 段階は対象外'),
    '共 {cue_total} 条字幕 · 高置信度 {confident} 条 · 建议检查 {suggested} 条 · 高风险 {high_risk} 条 · 预计人工审核约 {minutes} 分钟': ('Subtitles: {cue_total} · High confidence: {confident} · Suggested review: {suggested} · High risk: {high_risk} · Estimated manual review: {minutes} min', '字幕 {cue_total} 件 · 高信頼 {confident} 件 · 確認推奨 {suggested} 件 · 高リスク {high_risk} 件 · 手動確認の目安 {minutes} 分'),
    '填写 Base URL 与 API Key 后可获取模型；也可手动输入模型 ID': ('Enter Base URL and API Key to retrieve models, or enter a model ID manually', 'Base URL と API キーを入力してモデルを取得するか、モデル ID を手動で入力してください'),
    '正在取消测试…': ('Cancelling test…', 'テストをキャンセル中…'),
    'Codex：已登录/连接正常': ('Codex: signed in / connection ready', 'Codex：ログイン済み・接続正常'),
    '正在后台检查 CUDA；需要 CUDA 的组件：{value0}。选择组合时无需等待检查完成。': ('Checking CUDA in the background. Components requiring CUDA: {value0}. You can choose a combination before the check finishes.', 'CUDA をバックグラウンドで確認中。CUDA が必要な構成要素：{value0}。確認完了を待たずに組み合わせを選択できます。'),
    '已使用 {value0} · {value1}': ('Applied {value0} · {value1}', '{value0} を適用 · {value1}'),
    '已选择 {value0} 个素材': ('Media selected: {value0}', '選択したメディア：{value0} 件'),
    '方案切换失败，仍保留原方案：{exc}': ('Could not switch plans; previous plan kept: {exc}', 'プランを切り替えられませんでした。元のプランを維持しています：{exc}'),
    '方案保存失败：{exc}': ('Could not save plan: {exc}', 'プランを保存できませんでした：{exc}'),
    '当前使用：{value0}': ('Using: {value0}', '使用中：{value0}'),
    '尚未保存该服务商的 Key，请输入': ('No key saved for this provider. Enter one.', 'このプロバイダーのキーは未保存です。入力してください。'),
    '正在准备识别任务；临时转写将在实际批次完成后显示': ('Preparing recognition; provisional text appears after real batches finish', '認識を準備中。実際のバッチ処理が完了すると暫定テキストを表示します'),
    'CUDA 已就绪：{value0}。需要 CUDA 的组件：{value1}': ('CUDA ready: {value0}. Components requiring CUDA: {value1}', 'CUDA 準備完了：{value0}。CUDA が必要な構成要素：{value1}'),
    '当前设备还不能运行：{value0}。可换成轻量/在线组合，或修复 NVIDIA 驱动与 PyTorch。': ('This device cannot yet run: {value0}. Choose lightweight/online models or repair the NVIDIA driver and PyTorch.', '現在のデバイスでは実行できません：{value0}。軽量・オンラインモデルを選ぶか、NVIDIA ドライバーと PyTorch を修復してください。'),
    '工程记录读取失败：{exc}': ('Could not read project history: {exc}', 'プロジェクト履歴を読み込めませんでした：{exc}'),
    '最近用于类似素材：{value0} · {reason}，可从上方一键采用。': ('Recently used for similar media: {value0} · {reason}. Apply it above with one click.', '似たメディアで最近使用：{value0} · {reason}。上からワンクリックで適用できます。'),
    '术语增强 ON\n已绑定：{value0}{suffix}': ('Term Boost ON\nLinked: {value0}{suffix}', '用語補強 ON\n関連付け：{value0}{suffix}'),
    '识别已启动；上次运行配置保存失败：{exc}': ('Recognition started; could not save the last-run configuration: {exc}', '認識を開始しましたが、前回の実行設定を保存できませんでした：{exc}'),
    '这套自定义配置可从右侧菜单保存为方案。': ('Save this custom configuration as a plan using the menu on the right.', '右側のメニューから、このカスタム設定をプランとして保存できます。'),
    '{value0} 模型卡': ('{value0} model card', '{value0} モデルカード'),
    '选择': ('Select', '選択'),
    '保存当前帧的位置（独立于视频导出目录）': ('Saved-frame folder (independent of video export)', 'フレームの保存先（動画の書き出し先とは別）'),
    '当前': ('Current', '現在'),
    '之前': ('Previous', '前回'),
    '透明度': ('Transparency', '透明度'),
    '常用': ('Common', 'よく使う色'),
    '等比开关控制缩放 · 滚轮查看': ('Aspect lock controls scaling · Scroll to zoom', '縦横比ロックで拡大縮小を制御 · ホイールで表示倍率を変更'),
    '画布': ('Canvas', 'キャンバス'),
    '等比缩放': ('Lock Aspect Ratio', '縦横比を維持'),
    '锁定图层': ('Lock Layer', 'レイヤーをロック'),
    '画布尺寸': ('Canvas Size', 'キャンバスサイズ'),
    '宽度': ('Width', '幅'),
    '高度': ('Height', '高さ'),
    '底图布局': ('Background Layout', '背景の配置'),
    '应用画布尺寸与底图布局': ('Apply Canvas Size and Background Layout', 'キャンバスサイズと背景配置を適用'),
    '设置画布背景色 / 透明度': ('Canvas Background Color / Transparency', 'キャンバスの背景色・透明度'),
    '更换底图…（保留标题和贴图）': ('Replace Background… (Keep Titles and Overlays)', '背景を変更…（タイトルと画像を保持）'),
    '替换 / 重新定位素材…': ('Replace / Relocate Media…', 'メディアを差し替え・再指定…'),
    '移回画布中央': ('Move to Canvas Center', 'キャンバスの中央に移動'),
    '真实字重': ('Font Weight', '実際のウェイト'),
    '显示基础阴影': ('Show Basic Shadow', '基本の影を表示'),
    '多行对齐': ('Multiline Alignment', '複数行の配置'),
    '已选中多个图层。\n在画布中一起拖动，或复制 / 删除。\n锁定的图层不会移动或删除。': ('Multiple layers selected.\nDrag them together on the canvas, or copy/delete them.\nLocked layers will not move or be deleted.', '複数のレイヤーを選択しています。\nキャンバスで一緒に移動するか、コピー・削除できます。\nロックされたレイヤーは移動・削除しません。'),
    '封面编辑只影响独立封面工程。': ('Cover edits affect only the separate cover project.', 'サムネイルの編集は独立したサムネイルプロジェクトにのみ反映されます。'),
    '打开图片': ('Open Image', '画像を開く'),
    '同时把本次视频截图存入模板底图': ('Also include this video frame as the template background', '今回の動画フレームもテンプレートの背景として保存'),
    '格式': ('Format', '形式'),
    'JPEG 质量': ('JPEG Quality', 'JPEG 品質'),
    'JPEG 背景': ('JPEG Background', 'JPEG の背景'),
    '图层 · 拖动排序': ('Layers · Drag to Reorder', 'レイヤー · ドラッグで並べ替え'),
    '模板名称（保留标题、贴图和位置）': ('Template name (keeps titles, overlays, and positions)', 'テンプレート名（タイトル・画像・位置を保持）'),
    '封面精简工作区（下次启动）': ('Compact Cover Workspace (Next Launch)', 'サムネイル用の簡易ワークスペース（次回起動時）'),
    '完整工具 / 恢复默认工作区（下次启动）': ('Full Tools / Restore Default Workspace (Next Launch)', '全ツール・既定のワークスペースに戻す（次回起動時）'),
    '独立 GIMP 编辑窗口 · 已安装后的日常编辑无需联网': ('Separate GIMP window · Editing works offline after installation', '独立した GIMP 画面 · インストール後の編集はオフラインで利用可能'),
    '正在启动本地编辑器…': ('Starting local editor…', 'ローカルエディターを起動中…'),
    '应用标题': ('Apply Title', 'タイトルを適用'),
    '正在等待 GIMP 文档桥接…': ('Waiting for GIMP document connection…', 'GIMP 文書への接続を待機中…'),
    'GIMP：M 移动 · Shift+S 缩放 · 链条控制比例 · Enter 确认 / Esc 取消 · Ctrl+Z 撤销。\n在 GIMP 顶部“2ByteASR”菜单可返回、保存或导出；关闭此工作台会返回 Studio，GIMP 文档继续保留。': ("GIMP: M Move · Shift+S Scale · Chain locks aspect ratio · Enter Confirm / Esc Cancel · Ctrl+Z Undo.\nUse GIMP's 2ByteASR menu to return, save, or export. Closing this workspace returns to Studio and keeps the GIMP document open.", 'GIMP：M 移動 · Shift+S 拡大縮小 · 鎖で縦横比を維持 · Enter 確定 / Esc キャンセル · Ctrl+Z 元に戻す。\nGIMP の「2ByteASR」メニューから戻る・保存・書き出しができます。この画面を閉じると Studio に戻り、GIMP の文書は保持します。'),
    '填满（裁切超出画布部分）': ('Fill (Crop Outside Canvas)', '全面に配置（はみ出した部分を切り抜く）'),
    '适应（保留整张图片）': ('Fit (Keep Entire Image)', '全体を表示（画像を切り抜かない）'),
    '换图方式': ('Replacement Mode', '差し替え方法'),
    '焦点': ('Focus', '焦点'),
    '槽位随图层内部标识保存；改名、重排不影响。保存或更新模板后，下次复用生效。': ('Slots use internal layer IDs, so renaming and reordering are safe. Save or update the template to reuse them next time.', '置換箇所はレイヤー内部 ID で保存され、名前や順序の変更に影響されません。テンプレートを保存・更新すると次回も利用できます。'),
    '不指定': ('Unassigned', '未指定'),
    '当前截图': ('Current Frame', '現在のフレーム'),
    '新建封面': ('New Cover', '新規サムネイル'),
    '选择模板': ('Choose Template', 'テンプレートを選択'),
    '使用 / 更新当前帧': ('Use / Update Current Frame', '現在のフレームを使用・更新'),
    '换入本次 Studio 冻结帧（保留模板构图）': ('Use the captured Studio frame (keep template composition)', 'Studio で取得したフレームに差し替え（テンプレートの構図を保持）'),
    '下次按上次模板开始': ('Start with the last template next time', '次回は前回のテンプレートで開始'),
    '空白新建': ('Start Blank', '空白から作成'),
    '使用模板': ('Use Template', 'テンプレートを使用'),
    '查看执行过程': ('View Activity', '実行過程を表示'),
    '仅显示应用观察到的事件与公开摘要。当前服务未提供摘要时，不展示内部思考；无中间事件时无法判断内部进度。': ('Shows observed events and public summaries only. If no summary is provided, internal reasoning is not shown. Without intermediate events, internal progress is unknown.', '観測できたイベントと公開された要約のみを表示します。要約が提供されない場合、内部の思考は表示しません。途中のイベントがない場合は内部の進捗を判断できません。'),
    '跟随最新': ('Follow Latest', '最新に追従'),
    '复制脱敏过程': ('Copy Redacted Activity', '機密情報を除いた処理記録をコピー'),
    '输出位置': ('Output Location', '出力先'),
    '复制': ('Copy', 'コピー'),
    '在文件夹中显示': ('Show in Folder', 'フォルダーに表示'),
    '返回剪辑': ('Back to Editing', '編集に戻る'),
    '再次导出': ('Export Again', '再度書き出し'),
    '包含软件字幕': ('Include Studio Subtitles', 'Studio の字幕を含める'),
    '保存为 JPEG（默认 PNG）': ('Save as JPEG (Default: PNG)', 'JPEG で保存（既定：PNG）'),
    '更改保存帧目录…': ('Change Frame Folder…', 'フレーム保存先を変更…'),
    '打开最近保存的图片': ('Open Last Saved Image', '最後に保存した画像を開く'),
    '打开所在文件夹': ('Open Containing Folder', '保存先フォルダーを開く'),
    '全部变化': ('All Changes', 'すべての変更'),
    '跨游戏标记': ('Cross-game Flag', '別ゲームの用語'),
    '展开完整依据与来源': ('Expand Full Evidence and Sources', '根拠と参照元をすべて展開'),
    '复制详情': ('Copy Details', '詳細をコピー'),
    '仅选全部核心推荐': ('Select All Core Recommendations Only', '主要な推奨項目のみをすべて選択'),
    '批量勾选 ▾': ('Bulk Select ▾', '一括選択 ▾'),
    '应用所选': ('Apply Selected', '選択項目を適用'),
    '任务进行中——以下为已到手的候选快照；全部批次完成后打开正式预览应用。': ('Task running — these are available candidate snapshots. Open the final preview after all batches finish to apply them.', 'タスクを実行中です。取得済み候補のスナップショットを表示しています。全バッチ完了後に正式なプレビューから適用してください。'),
    '撤销所选合并': ('Undo Selected Merge', '選択した統合を取り消す'),
    '批量检查更新': ('Check Updates in Bulk', '更新を一括確認'),
    '按队列逐个游戏联网检查（不并行调用）；取消立即停止后续调度，已完成结果保留。': ('Check games online one at a time. Cancel stops scheduling immediately; completed results are kept.', 'ゲームを1つずつ順番にオンライン確認します。キャンセルすると以降の処理を停止し、完了した結果は保持します。'),
    '开始批量更新': ('Start Batch Update', '一括更新を開始'),
    '查看': ('View', '表示'),
    '继续': ('Continue', '続ける'),
    '来源回执与未完成项': ('Source Receipts and Unfinished Items', '参照元の記録と未完了項目'),
    '当前词条详情': ('Current Term Details', '現在の用語の詳細'),
    '任务仍在进行中——可先筛选查看，结束后才能应用。': ('Task still running — you can filter and inspect now, then apply when it finishes.', 'タスクは実行中です。絞り込みや閲覧は可能ですが、適用は完了後に行えます。'),
    '清空全部勾选（含筛选外）': ('Clear All Selections (Including Filtered-out Items)', '選択をすべて解除（絞り込み対象外も含む）'),
    '0 条参考': ('No references', '参考情報なし'),
    'AI 联网更新': ('AI Web Update', 'AI オンライン更新'),
    '批量更新…': ('Batch Update…', '一括更新…'),
    '更新记录': ('Update History', '更新履歴'),
    '确认所选参考': ('Confirm Selected References', '選択した参考情報を確認済みにする'),
    '隐藏所选': ('Hide Selected', '選択項目を非表示'),
    '待学习': ('Pending Learning', '学習待ち'),
    '加入项目词库': ('Add to Project Library', 'プロジェクトの用語集に追加'),
    '加入 Profile 词库': ('Add to Profile Library', 'プロファイルの用語集に追加'),
    '术语列表': ('Term List', '用語一覧'),
    '新建词库': ('New Term Library', '用語集を新規作成'),
    '导入词库': ('Import Term Library', '用語集をインポート'),
    '术语 / 错词 → 正确词': ('Term / Misspelling → Correct Term', '用語・誤表記 → 正しい用語'),
    '跟随全局校对 AI': ('Use Global Proofreading AI', '全体設定の校正 AI を使用'),
    '复制 AI 建词提示词': ('Copy AI Term-Building Prompt', 'AI 用語集作成のプロンプトをコピー'),
    '模型文件与 Python Runtime 分开统计。源码运行和正式 EXE 共用同一模型目录。': ('Model files and Python runtimes are counted separately. Source and EXE versions share the same model folder.', 'モデルファイルと Python 実行環境は別々に集計します。ソース版と EXE 版は同じモデル保存先を使用します。'),
    '扫描残留文件': ('Scan Leftover Files', '残存ファイルをスキャン'),
    '模型存储位置': ('Model Storage Location', 'モデルの保存先'),
    '更改': ('Change', '変更'),
    '扫描已有模型': ('Scan Existing Models', '既存モデルをスキャン'),
    '正在扫描模型文件与运行环境…': ('Scanning model files and runtimes…', 'モデルファイルと実行環境をスキャン中…'),
    '校验': ('Verify', '検証'),
    '打开目录': ('Open Folder', 'フォルダーを開く'),
    '2ByteASR 参考指数': ('2ByteASR Reference Index', '2ByteASR 参考指標'),
    '查看原始日志': ('View Raw Log', '元のログを表示'),
    '尚未启动': ('Not started', '未開始'),
    '模型详情': ('Model Details', 'モデルの詳細'),
    '工作方式': ('How It Works', '動作方式'),
    '选择本地人声验证样本': ('Choose a Local Speech Test Sample', 'ローカルの発話テスト音声を選択'),
    '可选：1–60 秒、16 kHz 单声道 WAV；仅本地处理': ('Optional: 1–60 s, 16 kHz mono WAV; processed locally only', '任意：1～60秒、16 kHz モノラル WAV。ローカルのみで処理'),
    '比较场景': ('Comparison Scenario', '比較する条件'),
    '</> 查看原始 JSON': ('</> View Raw JSON', '</> 元の JSON を表示'),
    '复制 JSON': ('Copy JSON', 'JSON をコピー'),
    '展开分段详情': ('Expand Segment Details', '区間の詳細を展開'),
    '可查看已保存的版本和动画。上次未完成的远端请求已停止；点击继续才会发起新请求。': ('View saved versions and animations. The previous unfinished remote request has stopped; a new request starts only when you choose Continue.', '保存済みのバージョンとアニメーションを確認できます。前回未完了のリモートリクエストは停止しています。「続ける」を選ぶと新しいリクエストを開始します。'),
    '从其他草稿记录继续…': ('Continue from Another Draft…', '他の下書きから続ける…'),
    '告诉 AI 怎么改这一稿（只改你提到的部分）：\n例如：金属感再重一点 / 文字不要黄色 / 边框更复杂 / 减少齿轮 / 入场再快一点 / 保留文字，只改背景': ('Tell AI how to revise this draft (only the parts you mention):\nFor example: more metallic / no yellow text / a more complex border / fewer gears / faster entrance / keep text, change only the background', 'この案の変更内容を AI に伝えてください（指定した部分のみ変更）：\n例：金属感を強くする／文字を黄色以外に／枠を複雑に／歯車を減らす／入場を速く／文字を残して背景だけ変更'),
    '仅调试模式显示。下面是 Provider 原始结构化响应，尚未经过 UI 摘要。': ("Debug mode only. This is the provider's raw structured response before UI summarization.", 'デバッグ時のみ表示します。画面用に要約する前の、プロバイダーの構造化応答です。'),
    '正在生成与成片一致的预览…': ('Generating a preview matching the final video…', '完成動画と同じ見た目のプレビューを生成中…'),
    '播放': ('Play', '再生'),
    '微调': ('Refine', '調整'),
    '恢复上一版': ('Restore Previous Version', '前のバージョンに戻す'),
    '隐藏': ('Hide', '非表示'),
    '已耗时 0:00 · 等待真实进展': ('Elapsed 0:00 · Waiting for progress', '経過 0:00 · 処理の進行を待機中'),
    '选择格式、说话人拆分方式和保存位置；导出后会自动回读验证。': ('Choose formats, speaker separation, and destination. Exported files are read back for verification.', '形式・話者別の分割方法・保存先を選択します。書き出したファイルは読み直して検証します。'),
    '说话人': ('Speakers', '話者'),
    '保存位置': ('Save Location', '保存先'),
    '选择文件夹': ('Choose Folder', 'フォルダーを選択'),
    '导出字幕视频': ('Export Subtitled Video', '字幕付き動画を書き出し'),
    '文件名': ('Filename', 'ファイル名'),
    '前后缀': ('Prefix / Suffix', '接頭辞・接尾辞'),
    '完整文件名': ('Full Filename', '完全なファイル名'),
    '字幕文件': ('Subtitle Files', '字幕ファイル'),
    '独立导出字幕文件，不会同时启动视频压制。': ('Export subtitle files separately, without starting video encoding.', '字幕ファイルだけを書き出します。動画のエンコードは開始しません。'),
    '复制路径': ('Copy Path', 'パスをコピー'),
    '另存为…': ('Save As…', '名前を付けて保存…'),
    '编码': ('Encoding', 'エンコード'),
    '质量': ('Quality', '品質'),
    '推荐：适合普通上传': ('Recommended for general uploads', '通常のアップロード向けの推奨設定'),
    '分辨率': ('Resolution', '解像度'),
    '自定义尺寸': ('Custom Size', 'カスタムサイズ'),
    '帧率': ('Frame Rate', 'フレームレート'),
    '自定义帧率': ('Custom Frame Rate', 'カスタムフレームレート'),
    '导出范围': ('Export Range', '書き出し範囲'),
    '音频': ('Audio', '音声'),
    'AAC 码率': ('AAC Bitrate', 'AAC ビットレート'),
    '编码器': ('Encoder', 'エンコーダー'),
    '质量控制方式': ('Quality Control Method', '品質の制御方法'),
    '目标码率': ('Target Bitrate', '目標ビットレート'),
    '最大码率': ('Maximum Bitrate', '最大ビットレート'),
    '编码速度': ('Encoding Speed', 'エンコード速度'),
    '导出预览': ('Export Preview', '書き出しプレビュー'),
    '▶ 播放': ('▶ Play', '▶ 再生'),
    '加入队列': ('Add to Queue', 'キューに追加'),
    '开始导出': ('Start Export', '書き出しを開始'),
    '正在压制字幕视频': ('Encoding Subtitled Video', '字幕付き動画をエンコード中'),
    '已用时 00:00': ('Elapsed 00:00', '経過 00:00'),
    '当前步骤  ·  准备工程': ('Current step · Preparing project', '現在の処理 · プロジェクトを準備'),
    '正在解析工程、检查输入文件并准备字幕。编码器尚未开始。': ('Reading the project, checking inputs, and preparing subtitles. Encoding has not started yet.', 'プロジェクトを解析し、入力ファイルと字幕を準備しています。エンコードはまだ開始していません。'),
    '无法开始导出': ('Cannot Start Export', '書き出しを開始できません'),
    '质量控制': ('Quality Control', '品質制御'),
    '兼容性与关键帧': ('Compatibility and Keyframes', '互換性とキーフレーム'),
    '输出摘要': ('Output Summary', '出力の概要'),
    '当前视频预览\n播放器将在 Studio 中复用': ('Current Video Preview\nUses the Studio player', '現在の動画プレビュー\nStudio のプレイヤーを使用します'),
    '设置入点  I': ('Set In Point  I', 'イン点を設定  I'),
    '设置出点  O': ('Set Out Point  O', 'アウト点を設定  O'),
    '返回设置': ('Back to Settings', '設定に戻る'),
    '安装渲染环境': ('Install Renderer', 'レンダラーをインストール'),
    '+ 添加颜色': ('+ Add Color', '+ 色を追加'),
    '角度': ('Angle', '角度'),
    '所有字体': ('All Fonts', 'すべてのフォント'),
    '反转': ('Reverse', '反転'),
    '匹配结果': ('Matches', '検索結果'),
    '压缩口播停顿': ('Shorten Speech Pauses', '発話の間を短縮'),
    '智能口播 · 本地人声检测': ('Smart Speech · Local Voice Detection', 'スマート発話 · ローカル人声検出'),
    '仅静音 · 低音量检测': ('Silence Only · Low-volume Detection', '無音のみ · 低音量検出'),
    '检测方式': ('Detection Method', '検出方式'),
    '当前可听音轨混音（保护所有人声）': ('Mix of Audible Tracks (Protect All Speech)', '現在聞こえるトラックのミックス（すべての発話を保護）'),
    '分析音轨': ('Analysis Tracks', '分析するトラック'),
    '停顿节奏': ('Pause Rhythm', '間のリズム'),
    '停顿时长 ≥': ('Pause Duration ≥', '間の長さ ≥'),
    '每侧各保留': ('Keep on Each Side', '前後それぞれに残す長さ'),
    '检测停顿': ('Detect Pauses', '間を検出'),
    '应用已勾选停顿': ('Apply Selected Pauses', '選択した間を適用'),
    '本地分析当前时间轴；背景声音可保留。先查看/试听候选，再一次应用；Ctrl+Z 撤销整批。混合音轨中的游戏台词同样保护。': ('Analyze the current timeline locally, retaining background audio if desired. Review/listen to candidates, then apply once; Ctrl+Z undoes the batch. Game dialogue in mixed audio is also protected.', '現在のタイムラインをローカルで分析します。背景音は保持できます。候補を確認・試聴してから一括適用し、Ctrl+Z で全件を取り消せます。混合音声内のゲームの台詞も保護します。'),
    'Skill：正在查找直播切片规则': ('Skill: looking for livestream clipping rules', 'Skill：ライブ切り抜きルールを検索中'),
    '跟随全局': ('Use Global Setting', '全体設定に従う'),
    '重命名': ('Rename', '名前を変更'),
    '从最近记录移除': ('Remove from Recent Projects', '最近使ったプロジェクトから削除'),
    '打开所在目录': ('Open Containing Folder', '保存先フォルダーを開く'),
    '删除工程': ('Delete Project', 'プロジェクトを削除'),
    '识别当前工程': ('Recognize Current Project', '現在のプロジェクトを認識'),
    '当前主页方案': ('Current Home Plan', 'ホームの現在のプラン'),
    '▸ 高级配置 · 模型': ('▸ Advanced Configuration · Models', '▸ 詳細設定 · モデル'),
    '统一字幕轨（默认，不额外运行说话人分离）': ('Single Subtitle Track (Default; No Extra Diarization)', '単一字幕トラック（既定・追加の話者分離なし）'),
    'Filetrans 原生分轨（使用所选 Filetrans 版本）': ('Filetrans Native Tracks (Selected Filetrans Version)', 'Filetrans の話者別トラック（選択したバージョンを使用）'),
    'Nemotron 3 独立说话人分析（需可选运行环境和模型）': ('Nemotron 3 Separate Speaker Analysis (Optional Runtime and Model Required)', 'Nemotron 3 による独立した話者分析（追加の実行環境・モデルが必要）'),
    '说话人：ECAPA 快速分离 · 不重复转写（身份需复核）': ('Speakers: ECAPA Fast Diarization · No Retranscription (Review Identities)', '話者：ECAPA 高速分離 · 再書き起こしなし（人物は要確認）'),
    '高级：按接口原始标签整理说话人': ('Advanced: Organize Speakers by Raw API Labels', '詳細：API の元のラベルで話者を整理'),
    '说话人：MOSS · 保留模型身份（主稿为其它模型时额外运行 MOSS）': ('Speakers: MOSS · Keep Model Identities (Extra MOSS Run When Another Model Transcribes)', '話者：MOSS · モデルの話者 ID を保持（他モデルで書き起こす場合は MOSS を追加実行）'),
    '仅本地识别与分轨（跳过云端校对和 AI 断句）': ('Local Recognition and Speaker Tracks Only (Skip Cloud Proofreading and AI Segmentation)', 'ローカル認識・話者別トラックのみ（クラウド校正・AI 分割を省略）'),
    '默认来自当前方案；此处选择仅影响本次识别，不修改其他方案或已有字幕。': ('Defaults come from the current plan. These choices apply only to this recognition task, not other plans or existing subtitles.', '現在のプランを既定値として使用します。ここでの選択は今回の認識にのみ適用し、他のプランや既存字幕は変更しません。'),
    '确认替换': ('Confirm Replacement', '置き換えを確認'),
    '在主页管理全部识别设置': ('Manage All Recognition Settings on Home', 'ホームですべての認識設定を管理'),
    '本次识别词库': ('Term Libraries for This Run', '今回の認識で使う用語集'),
    '未关联词库；可继续识别。': ('No linked term library; recognition can continue.', '関連付けた用語集はありません。認識は続行できます。'),
    '仅替换正式字幕稿；保留样式、剪辑和候选。': ('Replace only the main subtitles; keep styles, edits, and candidates.', '正式な字幕のみを置き換え、スタイル・編集・候補を保持します。'),
    '收藏': ('Favorite', 'お気に入り'),
    '描述': ('Description', '説明'),
    '播放性能': ('Playback Performance', '再生パフォーマンス'),
    '每 0.5 秒更新，发布帧率取最近 2 秒。耗时为有限样本的 P95；解码时差是帧与请求源时间之差。': ('Updates every 0.5 s; frame delivery uses the last 2 s. Durations show sample P95. Decode offset is the difference between a frame and its requested source time.', '0.5秒ごとに更新し、配信フレームレートは直近2秒から算出します。処理時間は標本の P95、デコード差はフレームと要求された元の時刻との差です。'),
    '复制诊断数据': ('Copy Diagnostics', '診断データをコピー'),
    '渲染预设': ('Render Preset', 'レンダリングプリセット'),
    'B站上传': ('Bilibili Upload', 'Bilibili アップロード'),
    '高压缩存档': ('High-compression Archive', '高圧縮の保存用'),
    '快速预览': ('Quick Preview', '高速プレビュー'),
    '输出': ('Output', '出力'),
    '输出格式': ('Output Format', '出力形式'),
    '可用编码器': ('Available Encoders', '利用可能なエンコーダー'),
    '固定码率': ('Constant Bitrate', '固定ビットレート'),
    '质量模式': ('Quality Mode', '品質モード'),
    '视频码率': ('Video Bitrate', '映像ビットレート'),
    '画面': ('Video', '映像'),
    '跟随源视频': ('Match Source Video', '元の動画に合わせる'),
    '自定义分辨率': ('Custom Resolution', 'カスタム解像度'),
    '直接复制': ('Stream Copy', 'そのままコピー'),
    '音频码率': ('Audio Bitrate', '音声ビットレート'),
    '采样率': ('Sample Rate', 'サンプルレート'),
    '声道': ('Channels', 'チャンネル'),
    '文件命名': ('File Naming', 'ファイルの命名'),
    '浏览': ('Browse', '参照'),
    '高级编码设置': ('Advanced Encoding Settings', '詳細エンコード設定'),
    '编码 Profile': ('Encoding Profile', 'エンコードプロファイル'),
    '编码 Level': ('Encoding Level', 'エンコードレベル'),
    '像素格式': ('Pixel Format', 'ピクセル形式'),
    '关键帧间隔': ('Keyframe Interval', 'キーフレーム間隔'),
    'B 帧': ('B-frames', 'B フレーム'),
    '字体目录': ('Font Folder', 'フォントフォルダー'),
    '预览 10 秒': ('Preview 10 Seconds', '10秒プレビュー'),
    '开始压制': ('Start Encoding', 'エンコードを開始'),
    '✓ 压制完成': ('✓ Encoding Complete', '✓ エンコード完了'),
    '其余证据已保存在字幕来源记录中': ('Other evidence is saved in the subtitle source records', 'その他の根拠は字幕の参照元記録に保存しています'),
    '点击当前快捷键后按键修改；保存后生效。': ('Click a shortcut and press new keys; changes take effect after saving.', '現在のショートカットをクリックして新しいキーを押してください。保存後に反映します。'),
    '恢复默认': ('Restore Defaults', '既定値に戻す'),
    '字幕样式': ('Subtitle Style', '字幕スタイル'),
    '整理只改变字幕归属，不证明声纹相同。所有批量操作都可一次撤销；原识别记录保留。': ('Organization changes subtitle ownership, not voice identity. Each bulk action can be undone once; original recognition records are kept.', '整理は字幕の割り当てを変更するだけで、同一人物であることを証明しません。一括操作は1回で元に戻せ、元の認識記録も保持します。'),
    '删除身份，字幕移到统一轨': ('Delete Identity; Move Subtitles to Unified Track', '話者を削除し、字幕を統合トラックに移動'),
    '删除所选人物及字幕': ('Delete Selected Speakers and Subtitles', '選択した話者と字幕を削除'),
    '全部合并为单轨': ('Merge All into One Track', 'すべて単一トラックに統合'),
    '按任务原始统计整理': ('Organize by Original Task Statistics', 'タスクの元の統計に基づいて整理'),
    '选择颜色': ('Choose Color', '色を選択'),
    '在成片中显示此说话人的字幕': ("Show This Speaker's Subtitles in the Final Video", 'この話者の字幕を完成動画に表示'),
    '应用修改': ('Apply Changes', '変更を適用'),
    '合并所选说话人': ('Merge Selected Speakers', '選択した話者を統合'),
    '将选中字幕归给此人': ('Assign Selected Subtitles to This Speaker', '選択した字幕をこの話者に割り当て'),
    '试听代表性语音': ('Play Representative Speech', '代表的な発話を試聴'),
    '设为主播': ('Set as Streamer', '配信者に指定'),
    '仅保留此说话人的字幕': ("Keep Only This Speaker's Subtitles", 'この話者の字幕のみ残す'),
    '选择本素材 MOSS 缓存': ('Choose MOSS Cache for This Media', 'このメディアの MOSS キャッシュを選択'),
    '用当前方案重新识别…': ('Recognize Again with Current Plan…', '現在のプランで再認識…'),
    '主要候选须超过原始发言数': ('Main candidates must exceed the original speech count', '主要候補は元の発話数を超える必要があります'),
    '默认样式': ('Default Style', '既定のスタイル'),
    '合并到': ('Merge Into', '統合先'),
    '试听': ('Listen', '試聴'),
    '自动预览 · 默认应用到当前字幕': ('Automatic Preview · Applies to Current Subtitle by Default', '自動プレビュー · 既定では現在の字幕に適用'),
    '背景框': ('Background Box', '背景枠'),
    '同时应用位置与缩放': ('Also Apply Position and Scale', '位置と拡大率も適用'),
    '混合': ('Mixed', '混在'),
    '线性渐变': ('Linear Gradient', '線形グラデーション'),
    '径向渐变（高级）': ('Radial Gradient (Advanced)', '放射状グラデーション（詳細）'),
    '视频预览：基础效果': ('Video Preview: Basic Effects', '動画プレビュー：基本効果'),
    '该说话人': ('This Speaker', 'この話者'),
    '全片': ('Entire Video', '動画全体'),
    '应用样式与动效': ('Apply Style and Animation', 'スタイルとアニメーションを適用'),
    '内置预设可从当前资料库隐藏并恢复；自定义与 AI 预设还可收藏、重命名、导入或导出。': ('Built-in presets can be hidden and restored. Custom and AI presets also support favorites, renaming, import, and export.', '内蔵プリセットは非表示・復元できます。カスタム・AI プリセットはお気に入り、名前の変更、インポート・書き出しも可能です。'),
    '批量选择': ('Bulk Selection', '一括選択'),
    '选择当前筛选结果中的预设': ('Select Presets in Current Filter', '現在の絞り込み結果のプリセットを選択'),
    '恢复内置': ('Restore Built-ins', '内蔵プリセットを復元'),
    '隐藏内置': ('Hide Built-ins', '内蔵プリセットを非表示'),
    '删除会隐藏内置预设，不会修改安装包资源': ('Deleting hides built-in presets without changing bundled resources', '削除すると内蔵プリセットを非表示にします。同梱リソースは変更しません'),
    '轨道音量…    G': ('Track Volume…    G', 'トラックの音量…    G'),
    '重新链接素材…': ('Relink Media…', 'メディアを再リンク…'),
    '轨道': ('Track', 'トラック'),
    '增益': ('Gain', 'ゲイン'),
    '左右拖动数值实时试听；Shift 精细，Ctrl 粗调。\n点击可输入；应用后保存，取消恢复原音量。': ('Drag horizontally to listen in real time; Shift for fine steps, Ctrl for coarse steps.\nClick to type. Apply saves changes; Cancel restores the previous volume.', '左右にドラッグしてリアルタイムに試聴できます。Shift で微調整、Ctrl で大きく調整。\nクリックで数値を入力し、適用で保存、キャンセルで元の音量に戻します。'),
    '将翻译当前工程的全部字幕并写入双语对照。': ('Translate all subtitles in this project and save them as bilingual text.', 'このプロジェクトのすべての字幕を翻訳し、対訳として保存します。'),
    '开始翻译': ('Start Translation', '翻訳を開始'),
    '目标语言': ('Target Language', '翻訳先の言語'),
    '当前字幕属性': ('Current Subtitle Properties', '現在の字幕のプロパティ'),
    '说话人：-': ('Speaker: -', '話者：-'),
    '字幕：-': ('Subtitle: -', '字幕：-'),
    '样式：-': ('Style: -', 'スタイル：-'),
    '显示当前 Cue 设置': ('Show Current Cue Settings', '現在の字幕設定を表示'),
    '拆分': ('Split', '分割'),
    '与下一条合并': ('Merge with Next', '次の字幕と結合'),
    '媒体信息': ('Media Information', 'メディア情報'),
    '拆分当前字幕': ('Split Current Subtitle', '現在の字幕を分割'),
    '删除当前字幕': ('Delete Current Subtitle', '現在の字幕を削除'),
    '智能修轴': ('Smart Timing Repair', '字幕時刻を自動修正'),
    '当前字幕试听': ('Preview Current Subtitle', '現在の字幕を試聴'),
    '播放一次': ('Play Once', '1回再生'),
    '循环播放': ('Loop Playback', 'ループ再生'),
    '整体偏移': ('Shift All Timing', '時刻をまとめてずらす'),
    '重命名轨道': ('Rename Track', 'トラック名を変更'),
    '轨道上移': ('Move Track Up', 'トラックを上へ'),
    '轨道下移': ('Move Track Down', 'トラックを下へ'),
    '音画同步校正…': ('Correct Audio/Video Sync…', '音声と映像の同期を調整…'),
    '移到 V1 并接在末尾': ('Move to V1 and Append at End', 'V1 の末尾に移動'),
    '删除主轨片段': ('Delete Main-track Clip', 'メイントラックのクリップを削除'),
    '移动片段到播放头': ('Move Clip to Playhead', 'クリップを再生ヘッドへ移動'),
    '设置源片段入点/出点…': ('Set Source In/Out Points…', '元のクリップのイン・アウト点を設定…'),
    '删除视频片段': ('Delete Video Clip', '動画クリップを削除'),
    '应用到所选范围': ('Apply to Selected Range', '選択範囲に適用'),
    '内置金样例与 AI 生成主题（AI 面板保存后自动出现在这里）。预览为真实 HTML/CSS 渲染，与导出一致。': ('Built-in examples and AI themes saved from the AI panel. Previews use real HTML/CSS rendering, matching export.', '内蔵サンプルと AI パネルで保存したテーマを表示します。プレビューは実際の HTML/CSS レンダリングで、書き出しと同じ見た目です。'),
    '刷新预览': ('Refresh Preview', 'プレビューを更新'),
    '就绪': ('Ready', '準備完了'),
    '把当前主题套用到范围': ('Apply Current Theme to Scope', '現在のテーマを指定範囲に適用'),
    '恢复原始主题': ('Restore Original Theme', '元のテーマに戻す'),
    '套用范围': ('Apply Scope', '適用範囲'),
    '单语': ('Single Language', '単一言語'),
    '开启 / 关闭双语显示': ('Toggle Bilingual Display', '対訳表示を切り替え'),
    'AI 翻译字幕…': ('AI Subtitle Translation…', 'AI 字幕翻訳…'),
    '[1–4] 采用并下一条   [↑↓] 切换   [Space] 重听   [E] 编辑   [R] 退出审核   [Enter] 当前正确': ('[1–4] Apply and next   [↑↓] Switch   [Space] Replay   [E] Edit   [R] Exit review   [Enter] Confirm current', '[1–4] 採用して次へ   [↑↓] 切り替え   [Space] 再試聴   [E] 編集   [R] 確認を終了   [Enter] 現在の字幕を確認'),
    '显示波形': ('Show Waveform', '波形を表示'),
    '跟随播放头': ('Follow Playhead', '再生ヘッドに追従'),
    '选中范围试跑': ('Trial Run on Selection', '選択範囲で試行'),
    '全工程执行': ('Run on Entire Project', 'プロジェクト全体で実行'),
    '技术详情 / 网络诊断': ('Technical Details / Network Diagnostics', '技術情報・ネットワーク診断'),
    '凭据：正在解析': ('Credentials: resolving', '認証情報：確認中'),
    '当前设计对象：未选择字幕': ('Design target: no subtitle selected', 'デザイン対象：字幕が未選択です'),
    '本地备选': ('Local Alternatives', 'ローカルの代替案'),
    '当前字幕尚未应用方案': ('No design applied to the current subtitle', '現在の字幕にはデザインが未適用です'),
    '可编辑主题 · 拖动字幕移动，拖动角点等比缩放；双击改字。': ('Editable theme · Drag to move, drag corners to scale proportionally, double-click to edit text.', '編集可能なテーマ · ドラッグで移動、角をドラッグで縦横比を維持して拡大縮小、ダブルクリックで文字を編集。'),
    '本地精修文字…': ('Refine Text Locally…', '文字をローカルで調整…'),
    '测量重叠 HTML 主题装饰…': ('Measure Overlapping HTML Decorations…', '重なった HTML 装飾を計測…'),
    '所有字幕操作…': ('All Subtitle Actions…', 'すべての字幕操作…'),
    '删除全部 AI 时保留收藏': ('Keep Favorites When Deleting All AI Designs', 'AI デザインの一括削除時にお気に入りを保持'),
    '删除选中': ('Delete Selected', '選択項目を削除'),
    '删除全部 AI': ('Delete All AI Designs', 'AI デザインをすべて削除'),
    '关闭预览': ('Close Preview', 'プレビューを閉じる'),
    '保留方案，稍后选择': ('Keep Options; Choose Later', '候補を残して後で選択'),
    '完整重做该方向…': ('Rebuild This Direction…', 'この方向性を作り直す…'),
    '字幕本体 · 拖动缩放查看字面、冰层与边缘；预览底色不随作品导出': ('Subtitle only · Drag and zoom to inspect text, ice layers, and edges. Preview background is not exported.', '字幕のみ · ドラッグと拡大で文字・氷の層・縁を確認できます。プレビューの背景色は書き出しに含みません。'),
    '播放字幕本体完整动画': ('Play Full Subtitle Animation', '字幕のアニメーション全体を再生'),
    '查看视频叠加 / 完整画面占比': ('View Video Overlay / Full-frame Coverage', '動画との合成・画面全体に対する大きさを確認'),
    '保留当前结构与正文，生成可撤销的本地修订。\n校验通过后自动应用；原稿与修改记录一起保存。': ('Keep the current structure and text, and generate an undoable local revision.\nApplies automatically after validation; the original and edit history are saved together.', '現在の構造と文字を維持し、元に戻せるローカル修正版を生成します。\n検証後に自動適用し、原本と変更履歴を一緒に保存します。'),
    'CLI Session：未知': ('CLI Session: unknown', 'CLI セッション：不明'),
    '登录': ('Sign In', 'ログイン'),
    '自动获取': ('Fetch Automatically', '自動取得'),
    '可用模型（自动）': ('Available Models (Automatic)', '利用可能なモデル（自動）'),
    'API 模型（可手动）': ('API Model (Manual Input Allowed)', 'API モデル（手動入力可）'),
    '转写风格': ('Transcription Style', '書き起こしスタイル'),
    '更新当前 Profile': ('Update Current Profile', '現在のプロファイルを更新'),
    '在线识别服务': ('Online Recognition Service', 'オンライン認識サービス'),
    '在线识别会使用所选服务商；本地模型组合不需要 Key。\n密钥会加密保存在本机。': ('Online recognition uses your selected provider. Local models do not need a key.\nKeys are encrypted and stored on this device.', 'オンライン認識は選択したプロバイダーを使用します。ローカルモデルにキーは不要です。\nキーは暗号化してこの端末に保存します。'),
    'OSS 临时中转存储': ('OSS Temporary Storage', 'OSS 一時ストレージ'),
    '识别结束后自动删除临时对象（48 小时后启动清理兜底）': ('Delete temporary objects after recognition (startup cleanup fallback after 48 hours)', '認識完了後に一時オブジェクトを削除（残存時は48時間後の起動時に削除）'),
    '音频会临时上传到你的 OSS 前缀并生成预签名 HTTPS 链接提交识别，结束后自动删除；AccessKey 只在本机签名，不会发送给识别服务。RAM 子账号最小权限：PutObject / GetObject / DeleteObject。': ('Audio is uploaded temporarily to your OSS prefix. A signed HTTPS URL is sent for recognition, then the object is deleted. AccessKey signs locally and is not sent to the recognition service. Minimum RAM permissions: PutObject / GetObject / DeleteObject.', '音声を OSS の指定プレフィックスに一時アップロードし、署名付き HTTPS URL を認識サービスに送ります。終了後に削除します。AccessKey はローカルでの署名にのみ使用し、認識サービスへは送信しません。RAM の最小権限：PutObject / GetObject / DeleteObject。'),
    '显示': ('Show', '表示'),
    '临时前缀': ('Temporary Prefix', '一時保存のプレフィックス'),
    '签名 URL 有效期（秒）': ('Signed URL Lifetime (Seconds)', '署名付き URL の有効期間（秒）'),
    '测试 OSS 连接': ('Test OSS Connection', 'OSS 接続をテスト'),
    '待处理': ('Pending', '待機中'),
})

# Conditional states and dialogs
STRINGS.update({
    '字幕本体 · {value0:g} 秒循环 · 中性底；全程保持统一放大比例': ('Subtitle only · {value0:g}-second loop · Neutral background; constant zoom throughout', '字幕のみ · {value0:g} 秒ループ · 無地の背景・一定の拡大率'),
    '保存这些设置更改吗？': ('Save these setting changes?', '設定の変更を保存しますか？'),
    '解锁图层': ('Unlock Layer', 'レイヤーのロックを解除'),
    '{value0}；可更改路径或素材后重试。': ('{value0}; change the path or media and try again.', '{value0}。パスや素材を変更して再試行できます。'),
    '封面有未保存修改': ('Unsaved Cover Changes', '表紙に未保存の変更があります'),
    '保存可编辑封面工程后再继续？': ('Save the editable cover project before continuing?', '編集可能な表紙プロジェクトを保存してから続けますか？'),
    '打开可编辑封面': ('Open Editable Cover', '編集可能な表紙を開く'),
    '多选图层': ('Multiple Layers', '複数のレイヤー'),
    '画布 · {value0} × {value1} px': ('Canvas · {value0} × {value1} px', 'キャンバス · {value0} × {value1} px'),
    '保存可编辑 PSD': ('Save Editable PSD', '編集可能な PSD を保存'),
    '已打开模板副本：{value0}；保存封面不会覆盖模板。': ('Template copy opened: {value0}. Saving the cover does not overwrite the template.', 'テンプレートのコピーを開きました：{value0}。表紙を保存してもテンプレートは上書きされません。'),
    '当前帧位于底层，但被不透明设计图层遮挡：{value0}。这些设计层已保留；在右侧图层列表取消其可见勾选即可看到当前帧。': ('The current frame is underneath opaque design layers: {value0}. These layers are preserved. Hide them in the layer list to see the frame.', '現在のフレームは不透明なデザインレイヤーの下にあります：{value0}。レイヤーは保持されています。右側のレイヤー一覧で非表示にするとフレームが見えます。'),
    '模板已保存：{value0}；下次可从“选择模板”打开。': ('Template saved: {value0}. Open it next time with “Choose Template”.', 'テンプレートを保存しました：{value0}。次回は「テンプレートを選択」から開けます。'),
    '保存可编辑封面工程后关闭？': ('Save the editable cover project before closing?', '編集可能な表紙プロジェクトを保存してから閉じますか？'),
    '{value0}已记住。请自行保存并关闭专用 GIMP，下次“使用 GIMP 编辑”生效；当前窗口不重启。': ('{value0} saved. Save and close the dedicated GIMP window yourself. The preference takes effect next time you choose “Edit in GIMP”; the current window stays open.', '{value0}を記憶しました。専用の GIMP で保存して閉じてください。次回の「GIMP で編集」から適用されます。現在のウィンドウは再起動しません。'),
    '{value0}；未报告保存成功，当前文档未关闭。': ('{value0}; saving was not confirmed, so the document remains open.', '{value0}。保存の成功を確認できないため、ドキュメントは開いたままです。'),
    '打开封面': ('Open Cover', '表紙を開く'),
    'PSD 导入兼容性': ('PSD Import Compatibility', 'PSD 読み込みの互換性'),
    '{value0}\n\n请检查图层并指定模板槽位，然后另存 XCF。': ('{value0}\n\nCheck the layers and assign template slots, then save as XCF.', '{value0}\n\nレイヤーを確認してテンプレートの差し替え先を指定し、XCF 形式で別名保存してください。'),
    '导出 PSD': ('Export PSD', 'PSD を書き出す'),
    '添加图片 / 透明贴图': ('Add Image / Transparent Overlay', '画像・透過画像を追加'),
    '更新模板': ('Update Template', 'テンプレートを更新'),
    '模板名称': ('Template Name', 'テンプレート名'),
    '导入封面模板': ('Import Cover Template', '表紙テンプレートを読み込む'),
    '已恢复 {value0} 的草稿。请检查后保存为 XCF；原手动保存文件未覆盖。': ('Draft recovered from {value0}. Review it and save as XCF. The previously saved file was not overwritten.', '{value0}の下書きを復元しました。内容を確認して XCF 形式で保存してください。手動で保存したファイルは上書きしていません。'),
    '添加应用专用字体': ('Add App Fonts', 'アプリ専用フォントを追加'),
    'PSD 交换格式限制': ('PSD Exchange Limitations', 'PSD 形式の制限'),
    '关闭封面': ('Close Cover', '表紙を閉じる'),
    '此文档有未保存修改。保存后关闭？': ('This document has unsaved changes. Save before closing?', '未保存の変更があります。保存してから閉じますか？'),
    '保存封面（XCF）': ('Save Cover (XCF)', '表紙を保存（XCF）'),
    '导出完成：{value0}': ('Export complete: {value0}', '書き出し完了：{value0}'),
    '模板已保存：{value0}。普通保存和草稿不会改动模板母版。': ('Template saved: {value0}. Normal saves and drafts do not change the template master.', 'テンプレートを保存しました：{value0}。通常の保存や下書き保存ではテンプレートの原本は変更されません。'),
    '缺少字体“{value0}”，当前替代为“{value1}”；原字体信息保留。': ('Font “{value0}” is missing; using “{value1}” for now. The original font choice is preserved.', 'フォント「{value0}」が見つからないため、現在は「{value1}」で代替しています。元のフォント指定は保持されています。'),
    '从图片制作封面': ('Create Cover from Image', '画像から表紙を作成'),
    '打开封面工程': ('Open Cover Project', '表紙プロジェクトを開く'),
    '制作封面失败：{value0}；可重试或从本地图片新建。': ('Could not create cover: {value0}. Retry or start from a local image.', '表紙を作成できませんでした：{value0}。再試行するか、ローカル画像から新規作成できます。'),
    '读取封面底图失败：{value0}': ('Could not read cover background: {value0}', '表紙の背景画像を読み込めませんでした：{value0}'),
    '重命名模板': ('Rename Template', 'テンプレート名を変更'),
    '删除模板': ('Delete Template', 'テンプレートを削除'),
    '从模板库移除“{value0}”？旧版本仍留在本机。': ('Remove “{value0}” from the template library? Older versions remain on this computer.', '「{value0}」をテンプレートライブラリから削除しますか？過去のバージョンはこの PC に残ります。'),
    '选择保存当前帧的目录': ('Choose a Folder for Saved Frames', 'フレームの保存先を選択'),
    '已保存帧：{value0}（菜单可打开）': ('Frame saved: {value0} (open from the menu)', 'フレームを保存しました：{value0}（メニューから開けます）'),
    '保存帧失败：{value0}；可在保存帧菜单更换目录。': ('Could not save frame: {value0}. Change the destination in the Save Frame menu.', 'フレームを保存できませんでした：{value0}。「フレームを保存」のメニューから保存先を変更できます。'),
    '· {value0}s 无事件': ('· No events for {value0}s', '· {value0}秒間イベントなし'),
    '应用所选（{value0}）': ('Apply Selected ({value0})', '選択項目を適用（{value0}）'),
    '{value0} 已确认 · {value1} 参考': ('{value0} confirmed · {value1} reference', '確認済み {value0}件 · 参考 {value1}件'),
    '{value0} 个游戏': ('Games: {value0}', 'ゲーム数：{value0}'),
    '{value0} 条已确认': ('Confirmed: {value0}', '確認済み：{value0}件'),
    '{value0} 条参考{value1}': ('Reference: {value0}{value1}', '参考：{value0}件{value1}'),
    '✓ 已用于本批字幕': ('✓ Used for this batch', '✓ 今回の字幕に使用中'),
    '删除所选术语（{value0}）': ('Delete Selected Terms ({value0})', '選択した用語を削除（{value0}）'),
    '已创建《{value0}》术语库': ('Created term library “{value0}”', '用語集「{value0}」を作成しました'),
    '本批字幕将使用《{value0}》术语库': ('This batch will use term library “{value0}”', '今回の字幕には用語集「{value0}」を使用します'),
    '恢复所选': ('Restore Selected', '選択項目を復元'),
    '已删除《{value0}》及其术语': ('Deleted “{value0}” and its terms', '「{value0}」とその用語を削除しました'),
    '《{value0}》没有可删除的用户术语': ('“{value0}” has no user terms to delete', '「{value0}」に削除可能なユーザー用語はありません'),
    '已添加术语：{value0}（《{value1}》）': ('Added term: {value0} (“{value1}”)', '用語を追加しました：{value0}（「{value1}」）'),
    '已批量导入 {value0} 条术语到《{value1}》': ('Imported {value0} terms into “{value1}”', '「{value1}」に {value0}件の用語を一括登録しました'),
    '本批已启用 {value0} 个词库': ('Term libraries enabled for this batch: {value0}', '今回有効な用語集：{value0}'),
    '已从本批移除《{value0}》': ('Removed “{value0}” from this batch', '今回の対象から「{value0}」を外しました'),
    '已将《{value0}》加入本批': ('Added “{value0}” to this batch', '今回の対象に「{value0}」を追加しました'),
    '已确认/学习映射会参与纠错；内置词库只提供弱候选，不会仅凭名字相似强制改字。\n\n专名 → 专名：拼写候选，只有读音和上下文支持时才修正；\n常见错词 → 正确词：保存明确纠错关系。': ('Confirmed and learned mappings are used for corrections. Built-in libraries supply weak candidates; similar names alone never force replacements.\n\nProper name → proper name: a spelling candidate, applied only when pronunciation and context support it.\nCommon error → correct term: an explicit correction mapping.', '確認済み・学習済みの対応は訂正に使用します。内蔵用語集は参考候補のみを提供し、名前が似ているだけで置き換えることはありません。\n\n固有名詞 → 固有名詞：表記の候補として扱い、発音と文脈が一致する場合のみ訂正します。\nよくある誤認識 → 正しい用語：明確な訂正の対応として保存します。'),
    '该游戏已有 {value0} 个内置参考词': ('This game has {value0} built-in reference terms', 'このゲームには {value0}件の内蔵参考用語があります'),
    '发现 {value0} 个候选（当前显示 {value1}）': ('Found {value0} candidates (showing {value1})', '{value0}件の候補を検出（{value1}件を表示中）'),
    '添加 {value0} 条到词库': ('Add {value0} Terms', '用語を {value0}件追加'),
    '已匹配内置参考 · {value0} 条参考词': ('Built-in reference matched · Terms: {value0}', '内蔵資料と一致 · 参考用語 {value0}件'),
    'AI 增强详情': ('AI Enhancement Details', 'AI 補助の詳細'),
    '选择模型存储位置': ('Choose Model Storage Location', 'モデルの保存先を選択'),
    '清理残留文件': ('Clean Up Residual Files', '残留ファイルを削除'),
    '将删除 {value0} 个项目内临时文件，共 {value1}：\n\n{value2}\n\n不会清理用户全局 Hugging Face cache。': ('Delete {value0} temporary files in this project, totaling {value1}:\n\n{value2}\n\nThe global Hugging Face cache will remain untouched.', 'このプロジェクト内の一時ファイル {value0}件（合計 {value1}）を削除します：\n\n{value2}\n\nユーザー共通の Hugging Face キャッシュは削除しません。'),
    '清理完成': ('Cleanup Complete', '削除完了'),
    '已删除 {value0} 个项目内临时文件。': ('Deleted {value0} temporary files in this project.', 'プロジェクト内の一時ファイルを {value0}件削除しました。'),
    '残留文件': ('Residual Files', '残留ファイル'),
    '没有发现可清理的 2ByteASR 临时下载文件。': ('No 2ByteASR temporary download files were found to clean up.', '削除可能な 2ByteASR の一時ダウンロードファイルはありません。'),
    '2ByteASR 参考指数 · {value0}': ('2ByteASR Reference Score · {value0}', '2ByteASR 参考指標 · {value0}'),
    '下载 {value0} - 2ByteASR': ('Download {value0} - 2ByteASR', '{value0}をダウンロード - 2ByteASR'),
    '选择短人声 WAV（仅本机验证）': ('Choose a Short Voice WAV (Local Test Only)', '短い人声音声の WAV を選択（ローカル検証のみ）'),
    '已安装 {value0} · 未安装 {value1}': ('Installed: {value0} · Not installed: {value1}', 'インストール済み {value0} · 未インストール {value1}'),
    '当前使用：{value0} · {value1}': ('Current: {value0} · {value1}', '使用中：{value0} · {value1}'),
    '确定卸载 {value0} 吗？\n\n文件会移动到项目的 model_trash 目录，可手动恢复。': ("Uninstall {value0}?\n\nFiles will be moved to the project's model_trash folder and can be restored manually.", '{value0}をアンインストールしますか？\n\nファイルはプロジェクトの model_trash フォルダーに移動され、手動で復元できます。'),
    '模型已卸载': ('Model Uninstalled', 'モデルをアンインストールしました'),
    '已移动到：\n{value0}': ('Moved to:\n{value0}', '移動先：\n{value0}'),
    '识别方案 · {value0}': ('Recognition Plan · {value0}', '認識プラン · {value0}'),
    '当前：{value0}': ('Current: {value0}', '現在：{value0}'),
    '预计新增下载：{value0}': ('Estimated Download: {value0}', '追加ダウンロード予定：{value0}'),
    '正在使用这个模型': ('This Model Is in Use', 'このモデルは使用中です'),
    '请先为当前角色选择另一个模型，再卸载。': ('Select another model for this role before uninstalling.', 'アンインストールする前に、この役割に別のモデルを選択してください。'),
    '已选用 {value0}{value1}': ('Selected {value0}{value1}', '{value0}{value1}を選択しました'),
    '当前方案已启用 ✓': ('Enabled in the current plan ✓', '現在のプランで有効 ✓'),
    '当前方案已选 · 需修复环境': ('Selected · Environment repair required', '選択済み · 環境の修復が必要です'),
    '重复 ASR 证据': ('Duplicate ASR Evidence', 'ASR の証拠が重複しています'),
    '主力转写与文字复核使用同一模型时，无法提供独立 ASR 证据。\n\n默认不推荐这样配置；高级用户仍可继续。': ('Using the same model for transcription and text review provides no independent ASR evidence.\n\nThis configuration is not recommended, but advanced users can continue.', '書き起こしとテキスト確認に同じモデルを使用すると、独立した ASR の証拠を得られません。\n\n推奨される設定ではありませんが、内容を理解したうえで続行できます。'),
    '显存可能不足': ('GPU Memory May Be Insufficient', 'GPU メモリが不足する可能性があります'),
    '检测到 {value0}（{value1:.1f} GiB）。\n\nOmnilingual ASR LLM 7B 官方 BF16 推理约需 17 GiB 显存，当前 GPU 可能无法完整加载。你仍然可以先下载模型文件。': ('Detected {value0} ({value1:.1f} GiB).\n\nOmnilingual ASR LLM 7B requires about 17 GiB of GPU memory for official BF16 inference. This GPU may not load it fully. You can still download the model files.', '検出された GPU：{value0}（{value1:.1f} GiB）。\n\nOmnilingual ASR LLM 7B の公式 BF16 推論には約 17 GiB の GPU メモリが必要です。完全に読み込めない可能性がありますが、モデルファイルのダウンロードは可能です。'),
    '卸载失败': ('Uninstall Failed', 'アンインストールに失敗しました'),
    '{value0}{value1} 没有该文件': ('{value0}{value1} does not have this file', '{value0}{value1}にこのファイルはありません'),
    '自动回退 {value0}/{value1}：正在尝试 {value2}{value3}': ('Fallback {value0}/{value1}: trying {value2}{value3}', '代替先 {value0}/{value1}：{value2}{value3}を試行中'),
    '正在从 {value0}{value1} 下载': ('Downloading from {value0}{value1}', '{value0}{value1}からダウンロード中'),
    '</> 收起原始 JSON': ('</> Hide Raw JSON', '</> 生の JSON を閉じる'),
    '收起分段详情': ('Hide Segment Details', '区間の詳細を閉じる'),
    '选择已保存的 AI 草稿记录': ('Choose a Saved AI Draft', '保存済みの AI 下書きを選択'),
    'Remotion 新预览': ('New Remotion Preview', '新しい Remotion プレビュー'),
    '⚡ 高保真预览不可用 · 保留上个有效预览': ('⚡ Fidelity preview unavailable · Keeping the last valid preview', '⚡ 高精度プレビューを利用できません · 直前の有効なプレビューを保持'),
    '⚡ 高保真预览不可用 · 已回退可读近似': ('⚡ Fidelity preview unavailable · Using a readable approximation', '⚡ 高精度プレビューを利用できません · 読める簡易表示に切り替え'),
    '取消准备': ('Cancel Preparation', '準備をキャンセル'),
    '正在准备设计': ('Preparing Design', 'デザインを準備中'),
    '设计尚未生成': ('No Design Generated Yet', 'デザインはまだ生成されていません'),
    '动画预览失败：{value0}\n六帧保留，可重试预览': ('Animation preview failed: {value0}\nSix frames are preserved. You can retry the preview.', 'アニメーションのプレビューに失敗しました：{value0}\n6枚のフレームは保持されています。再試行できます。'),
    '已把特效主题套用到 {value0} 条字幕': ('Applied the effect theme to {value0} subtitles', '{value0}件の字幕にエフェクトテーマを適用しました'),
    '没有可套用的字幕': ('No Subtitles to Apply To', '適用できる字幕がありません'),
    '选择档案保存位置': ('Choose Archive Destination', 'アーカイブの保存先を選択'),
    '选择字幕特效档案': ('Choose a Subtitle Effect Archive', '字幕エフェクトのアーカイブを選択'),
    '重试 Provider': ('Retry Provider', 'プロバイダーを再試行'),
    '{value0} · 可使用本地备选': ('{value0} · Local alternative available', '{value0} · ローカルの代替案を利用できます'),
    '可直接实时预览': ('Ready for Live Preview', 'リアルタイムでプレビューできます'),
    '复杂视觉方案 · 预览与成片使用同一视觉配方': ('Advanced design · Preview and final video use the same visual recipe', '高度なデザイン · プレビューと完成動画に同じ描画設定を使用'),
    '生成已取消': ('Generation Cancelled', '生成をキャンセルしました'),
    'Provider 未完成': ('Provider Did Not Complete', 'プロバイダーの処理が完了しませんでした'),
    '未生成本地备选': ('No Local Alternative Generated', 'ローカルの代替案は未生成です'),
    '可根据具体错误重试 Provider': ('Retry the provider after checking the error', 'エラー内容を確認してプロバイダーを再試行できます'),
    '已保存到 Style Library；Motion 仍可单独在 Motion Library 管理': ('Saved to Style Library. Motion can still be managed separately in Motion Library.', 'スタイルライブラリに保存しました。動きはモーションライブラリで個別に管理できます。'),
    '未安装 · {value0}': ('Not installed · {value0}', '未インストール · {value0}'),
    '服务能力声明（尚未实测）：{value0}': ('Declared capabilities (not yet tested): {value0}', 'サービスが宣言している機能（未検証）：{value0}'),
    '{value0} 凭据已配置（连接状态另行检测）': ('{value0} credentials configured (connection checked separately)', '{value0}の認証情報は設定済みです（接続は別途確認）'),
    '{value0} 未配置': ('{value0} not configured', '{value0}は未設定です'),
    '{value0}…（见技术详情）': ('{value0}… (see technical details)', '{value0}…（技術詳細を参照）'),
    '{value0}\n请求：{value1}': ('{value0}\nRequest: {value1}', '{value0}\nリクエスト：{value1}'),
    '没有可编辑的字幕': ('No Editable Subtitles', '編集可能な字幕がありません'),
    '当前字幕不是 AI 特效字幕——先在 AI 面板生成或从特效字幕库套用': ('This subtitle has no AI effect. Generate one in the AI panel or apply one from the effect library first.', 'この字幕に AI エフェクトはありません。AI パネルで生成するか、エフェクト字幕ライブラリから適用してください。'),
    '将请求 AI：{value0}': ('AI request: {value0}', 'AI への依頼：{value0}'),
    '输入修改要求发送，或展开快速调整选择字体/字号/颜色': ('Enter changes to send, or expand Quick Adjustments to choose font, size and color', '変更内容を入力して送信するか、クイック調整を開いてフォント・サイズ・色を選択してください'),
    '当前字幕不是 AI 特效字幕': ('This Subtitle Has No AI Effect', 'この字幕に AI エフェクトはありません'),
    '请先选择字体/字号/颜色，或在补充要求里输入修改意见': ('Choose a font, size or color, or enter additional changes first', 'フォント・サイズ・色を選択するか、追加の要望を入力してください'),
    '所选范围内没有 AI 特效字幕': ('No AI Effect Subtitles in This Range', '選択範囲に AI エフェクト字幕はありません'),
    '请先生成或导入一个网页主题': ('Generate or import a web theme first', '先に Web テーマを生成または読み込んでください'),
    '当前草稿尚未通过渲染校验，不能导出': ('The draft has not passed render validation and cannot be exported', '描画検証に合格していないため、この下書きは書き出せません'),
    '使用成片渲染器生成{value0}': ('Generated with the final-video renderer{value0}', '完成動画のレンダラーで生成{value0}'),
    '当前没有可查看的 AI 原始响应': ('No Raw AI Response to Show', '表示できる AI の生の応答はありません'),
    '网页主题「{value0}」已保存到样式库；可在「特效字幕库」查看真实预览': ('Web theme “{value0}” saved to Style Library. View its real preview in the effect library.', 'Web テーマ「{value0}」をスタイルライブラリに保存しました。エフェクト字幕ライブラリで実際のプレビューを確認できます。'),
    '请先生成视觉方案': ('Generate a Visual Design First', '先にビジュアルデザインを生成してください'),
    '正在生成设计…\n请求：{value0}': ('Generating design…\nRequest: {value0}', 'デザインを生成中…\nリクエスト：{value0}'),
    '当前特效：{value0}{value1}{value2}': ('Current effect: {value0}{value1}{value2}', '現在のエフェクト：{value0}{value1}{value2}'),
    '范围应用未完成；已应用字幕保留，可重试：{value0}': ('Range application incomplete. Applied subtitles are preserved; retry: {value0}', '範囲への適用が完了しませんでした。適用済みの字幕は保持されています。再試行できます：{value0}'),
    '档案导入失败：{value0}': ('Archive import failed: {value0}', 'アーカイブの読み込みに失敗しました：{value0}'),
    '质量校验通过': ('Quality Validation Passed', '品質検証に合格'),
    '设计方向': ('Design Direction', 'デザインの方向性'),
    '当前草稿尚未通过渲染校验，不能应用': ('The draft has not passed render validation and cannot be applied', '描画検証に合格していないため、この下書きは適用できません'),
    '当前草稿尚未通过渲染校验，不能保存': ('The draft has not passed render validation and cannot be saved', '描画検証に合格していないため、この下書きは保存できません'),
    '已修正时间轴 {value0:+d}ms / {value1:+d}ms': ('Timing corrected by {value0:+d}ms / {value1:+d}ms', '時刻を {value0:+d}ms / {value1:+d}ms 補正しました'),
    '已修正 {value0} 条字幕，跳过 {value1} 条': ('Corrected {value0} subtitles; skipped {value1}', '{value0}件の字幕を補正し、{value1}件をスキップしました'),
    '已按字词分配文字，保留手动切点{value0}': ('Text split using word timings; manual cut point preserved{value0}', '単語の時刻に従って文字を分割しました。手動の切断位置は保持されています{value0}'),
    '缺少可匹配字词时间：文字按比例分配，请试听检查切点': ('No matching word timings. Text was split proportionally; listen to check the cut.', '対応する単語時刻がないため、文字数に応じて分割しました。音声を聞いて切断位置を確認してください。'),
    '无法可靠修轴：当前字幕缺少明确字级时间或语音证据': ('Cannot correct timing reliably: this subtitle lacks clear word timings or speech evidence', '明確な単語時刻や発話の証拠がないため、信頼できる時刻補正を行えません'),
    '无法可靠修轴：已跳过 {value0} 条': ('Cannot correct timing reliably; skipped {value0} subtitles', '信頼できる時刻補正を行えず、{value0}件をスキップしました'),
    '已整体偏移 {value0:+d}ms（{value1} 条）': ('Shifted {value1} subtitles by {value0:+d}ms', '{value1}件の字幕を {value0:+d}ms 移動しました'),
    '选择字幕保存文件夹': ('Choose Subtitle Output Folder', '字幕の保存先フォルダーを選択'),
    '▸ 运行详情': ('▸ Run Details', '▸ 実行の詳細'),
    'Ⅱ 暂停': ('Ⅱ Pause', 'Ⅱ 一時停止'),
    '码率': ('Bitrate', 'ビットレート'),
    '另存为导出预设': ('Save As Export Preset', '書き出しプリセットとして保存'),
    '预设名称': ('Preset Name', 'プリセット名'),
    '选择导出目录': ('Choose Export Folder', '書き出し先を選択'),
    '压制耗时  {value0}': ('Encoding time  {value0}', 'エンコード時間  {value0}'),
    '高级字幕渲染环境已安装，可以重试。': ('The advanced subtitle renderer is installed. You can retry.', '高度な字幕の描画環境をインストールしました。再試行できます。'),
    '高级字幕渲染环境安装失败，请查看详情。': ('The advanced subtitle renderer could not be installed. See details.', '高度な字幕の描画環境をインストールできませんでした。詳細を確認してください。'),
    '已用时 {value0}{value1}': ('Elapsed {value0}{value1}', '経過時間 {value0}{value1}'),
    '已替换下一条（可 Ctrl+Z 撤销）': ('Replaced next match (Ctrl+Z to undo)', '次の一致箇所を置換しました（Ctrl+Z で元に戻す）'),
    '已替换 {value0} 处，涉及 {value1} 条字幕（可 Ctrl+Z 一次撤销）': ('Replaced {value0} matches in {value1} subtitles (one Ctrl+Z undoes all)', '{value1}件の字幕で {value0}箇所を置換しました（Ctrl+Z 1回で全て元に戻せます）'),
    '重命名工程': ('Rename Project', 'プロジェクト名を変更'),
    '工程名称': ('Project Name', 'プロジェクト名'),
    '重新链接素材': ('Relink Media', '素材を再リンク'),
    '无法使用所选素材': ('Cannot Use Selected Media', '選択した素材を使用できません'),
    '所选素材与原素材不一致': ('Selected Media Does Not Match the Original', '選択した素材が元の素材と一致しません'),
    '{value0}\n\n仍要重新链接并保留现有剪辑吗？': ('{value0}\n\nRelink anyway and keep the existing edits?', '{value0}\n\n既存の編集を保持したまま再リンクしますか？'),
    '导入字幕': ('Import Subtitles', '字幕を読み込む'),
    '当前字幕 {value0} 条；识别结果将替换字幕，保留样式和剪辑。': ('Current subtitles: {value0}. Recognition replaces them while preserving styles and edits.', '現在の字幕は {value0}件です。認識結果で字幕を置き換えます。スタイルと編集は保持されます。'),
    '使用所选方案生成工程字幕。': ('Generate project subtitles with the selected plan.', '選択したプランでプロジェクトの字幕を生成します。'),
    '识别并替换当前字幕': ('Transcribe and Replace Subtitles', '認識して字幕を置き換え'),
    '素材已加入媒体池': ('Added to Media Pool', 'メディアプールに追加しました'),
    '已选 {value0} 个词库：{value1}…': ('Selected term libraries ({value0}): {value1}…', '選択中の用語集（{value0}）：{value1}…'),
    '已选 {value0} 个词库：{value1}': ('Selected term libraries ({value0}): {value1}', '選択中の用語集（{value0}）：{value1}'),
    '{value0} 高级配置 · 模型': ('{value0} Advanced · Models', '{value0} 詳細設定 · モデル'),
    'V1 由主素材剪辑维护；新素材请选择 V2 或新建视频轨。': ('V1 is managed by the main media edits. Choose V2 or create a video track for new media.', 'V1 は主素材の編集に使用します。新しい素材には V2 または新規映像トラックを選択してください。'),
    '移除未使用素材': ('Remove Unused Media', '未使用の素材を除去'),
    '从当前工程移除 {value0} 个未使用素材？\n源文件不会被删除。': ('Remove {value0} unused media items from this project?\nSource files will not be deleted.', '未使用の素材 {value0}件をこのプロジェクトから除去しますか？\n元のファイルは削除しません。'),
    '无法添加片段': ('Cannot Add Clip', 'クリップを追加できません'),
    '取消收藏': ('Remove from Favorites', 'お気に入りを解除'),
    '打开 Subtitle Project': ('Open Subtitle Project', '字幕プロジェクトを開く'),
    '说话人管理 · 待应用': ('Speaker Management · Changes Pending', '話者管理 · 未適用の変更'),
    '说话人管理 · 待确认': ('Speaker Management · Confirmation Needed', '話者管理 · 確認待ち'),
    '检测到多个持续说话人，需要确认。打开全部 MOSS 标签试听并恢复轨道。': ('Several persistent speakers were detected. Open all MOSS labels to listen and restore tracks.', '継続的に発話する複数の話者が検出されました。MOSS の全ラベルを開き、試聴してトラックを復元してください。'),
    '保存 Subtitle Project': ('Save Subtitle Project', '字幕プロジェクトを保存'),
    '输出视频': ('Output Video', '出力動画'),
    '压制已取消': ('Encoding Cancelled', 'エンコードをキャンセルしました'),
    '正在压制 {value0}': ('Encoding {value0}', 'エンコード中 {value0}'),
    '审核进度  {value0} / {value1}': ('Review progress  {value0} / {value1}', '確認の進捗  {value0} / {value1}'),
    '退出审核模式': ('Exit Review Mode', '確認モードを終了'),
    '■ 退出审核': ('■ Exit Review', '■ 確認を終了'),
    '快捷键冲突：{value0}': ('Shortcut conflicts: {value0}', 'ショートカットの競合：{value0}'),
    '未发现快捷键冲突': ('No Shortcut Conflicts', 'ショートカットの競合はありません'),
    '选择含 moss.json 的缓存目录': ('Choose a Cache Folder Containing moss.json', 'moss.json を含むキャッシュフォルダーを選択'),
    '{value0} · {value1} 预计说话人数：{value2}。标签不等于真人身份，请按原音确认归属。\n先按需试听（每次 2–4 秒，不自动播放），再标记主要说话人 / 游戏或节目声 / 忽略。{value3}应用复用人工字幕；不请求模型。': ('{value0} · {value1} Expected speakers: {value2}. Labels are not verified identities; confirm them by listening.\nListen as needed (2–4 seconds each, never automatic), then classify as main speaker, game/program audio, or ignore. {value3}Applying reuses edited subtitles and makes no model requests.', '{value0} · {value1} 想定話者数：{value2}。ラベルは本人の識別情報ではありません。音声を聞いて確認してください。\n必要に応じて試聴し（各2～4秒、自動再生なし）、主要話者・ゲームや番組の音声・無視に分類してください。{value3}適用時は編集済み字幕を再利用し、モデルへのリクエストは行いません。'),
    '{value0}主要说话人：{value1}；预计 {value2} 条轨道 / {value3} cue；并入 {value4} 个标签，忽略/待恢复 {value5} 个。\n{value6}': ('{value0}Main speakers: {value1}; expected {value2} tracks / {value3} cues; merging {value4} labels, ignoring/awaiting recovery: {value5}.\n{value6}', '{value0}主要話者：{value1}。予定：{value2}トラック／{value3}字幕。統合するラベル：{value4}、無視・復元待ち：{value5}。\n{value6}'),
    '删除人物及字幕': ('Delete Speakers and Subtitles', '話者と字幕を削除'),
    '删除 {value0} 个身份及 {value1} 条字幕？可在 Studio 撤销。': ('Delete {value0} identities and {value1} subtitles? This can be undone in Studio.', '{value0}人の話者と {value1}件の字幕を削除しますか？Studio で元に戻せます。'),
    '{value0}  高级设置': ('{value0}  Advanced Settings', '{value0}  詳細設定'),
    '动效 · AI / Graph Motion\n{value0}': ('Motion · AI / Graph Motion\n{value0}', '動き · AI / Graph Motion\n{value0}'),
    '✓ 视觉方案已保存；预览与成片使用同一渲染链': ('✓ Design saved; preview and final video use the same renderer', '✓ デザインを保存しました。プレビューと完成動画に同じレンダラーを使用します'),
    '✓ 字幕样式已应用并进入实时预览': ('✓ Subtitle style applied to live preview', '✓ 字幕スタイルを適用し、リアルタイムプレビューに反映しました'),
    '已移除复杂视觉效果，预览回到基础模式': ('Advanced visuals removed; preview returned to basic mode', '高度な視覚効果を除去し、基本プレビューに戻しました'),
    '已隐藏内置预设 · 可在预设管理器恢复': ('Built-in preset hidden · Restore it in Preset Manager', '内蔵プリセットを非表示にしました · プリセット管理から復元できます'),
    '已删除自定义预设': ('Custom Preset Deleted', 'カスタムプリセットを削除しました'),
    '已应用预设「{value0}」': ('Applied preset “{value0}”', 'プリセット「{value0}」を適用しました'),
    '已复制字幕样式（不含文字、时间、说话人与位置）': ('Subtitle style copied (excluding text, timing, speakers and position)', '字幕スタイルをコピーしました（文字・時刻・話者・位置は含みません）'),
    '已粘贴样式到 {value0} 条字幕': ('Pasted style to {value0} subtitles', '{value0}件の字幕にスタイルを貼り付けました'),
    '{value0}快速调整：字体 / 字号 / 颜色': ('{value0}Quick Adjustments: Font / Size / Color', '{value0}クイック調整：フォント・サイズ・色'),
    '⚡ 复杂视觉 · 自动使用高保真渲染': ('⚡ Advanced visuals · Fidelity renderer selected automatically', '⚡ 高度な視覚効果 · 高精度レンダラーを自動で使用'),
    '⚡ 径向复杂视觉 · 自动使用高保真渲染': ('⚡ Radial visuals · Fidelity renderer selected automatically', '⚡ 放射状の視覚効果 · 高精度レンダラーを自動で使用'),
    '当前字幕没有复杂视觉效果': ('This Subtitle Has No Advanced Visuals', 'この字幕に高度な視覚効果はありません'),
    '样式预设未保存：{value0}': ('Style preset was not saved: {value0}', 'スタイルプリセットを保存できませんでした：{value0}'),
    '动效预设未保存：{value0}': ('Motion preset was not saved: {value0}', 'モーションプリセットを保存できませんでした：{value0}'),
    '网页主题的阴影由主题 HTML/CSS 控制；请在 AI 面板中修改主题，数值控件不支持直接覆盖。': ('Web theme shadows are controlled by theme HTML/CSS. Edit the theme in the AI panel; numeric controls cannot override them directly.', 'Web テーマの影はテーマの HTML/CSS で制御します。AI パネルでテーマを変更してください。数値コントロールから直接上書きすることはできません。'),
    '启用开源字体': ('Enable Open-Source Fonts', 'オープンソースフォントを有効にする'),
    '仅在你确认后，2ByteASR 才会启用随应用提供的字体文件。\n不会联网下载，也不会修改 Windows 系统字体。\n\n{value0}\n\n继续检查并启用？': ('2ByteASR will enable bundled fonts only after you confirm.\nNothing is downloaded and Windows system fonts remain unchanged.\n\n{value0}\n\nCheck and enable them?', '確認後、2ByteASR に同梱されたフォントを有効にします。\nダウンロードは行わず、Windows のシステムフォントも変更しません。\n\n{value0}\n\n確認して有効にしますか？'),
    '已启用：{value0}': ('Enabled: {value0}', '有効にしました：{value0}'),
    '字体已启用': ('Fonts Enabled', 'フォントを有効にしました'),
    '已为本次应用会话启用开源字体。': ('Open-source fonts are enabled for this app session.', 'このアプリのセッションでオープンソースフォントを有効にしました。'),
    '未找到随包字体': ('Bundled Fonts Not Found', '同梱フォントが見つかりません'),
    '当前安装包没有包含字体文件，2ByteASR 将继续使用安全回退字体。\n\n可从以下官方项目自行获取：\n{value0}': ('This package contains no font files. 2ByteASR will keep using safe fallback fonts.\n\nYou can obtain fonts from these official projects:\n{value0}', 'このパッケージにはフォントファイルがありません。引き続き安全な代替フォントを使用します。\n\n次の公式プロジェクトから入手できます：\n{value0}'),
    '退出批量选择': ('Exit Multi-Select', '複数選択を終了'),
    '已删除 {value0} 个预设': ('Deleted {value0} presets', '{value0}件のプリセットを削除しました'),
    '没有选中可删除的预设': ('No Deletable Presets Selected', '削除可能なプリセットが選択されていません'),
    '已隐藏 {value0} 个内置预设': ('Hidden built-in presets: {value0}', '内蔵プリセットを {value0}件非表示にしました'),
    '已删除 {value0} 个 AI 预设': ('Deleted {value0} AI presets', '{value0}件の AI プリセットを削除しました'),
    '重命名预设': ('Rename Preset', 'プリセット名を変更'),
    '导出样式预设': ('Export Style Preset', 'スタイルプリセットを書き出す'),
    '导入样式预设': ('Import Style Preset', 'スタイルプリセットを読み込む'),
    '请选择一个自定义或 AI 预设': ('Select a Custom or AI Preset', 'カスタムまたは AI プリセットを選択してください'),
    '已导出 {value0} 个预设': ('Exported {value0} presets', '{value0}件のプリセットを書き出しました'),
    '已导入 {value0} 个预设': ('Imported {value0} presets', '{value0}件のプリセットを読み込みました'),
    '已恢复 {value0} 个内置预设': ('Restored {value0} built-in presets', '{value0}件の内蔵プリセットを復元しました'),
    '暂无可用预览 · 原稿已保存': ('No Preview Available · Original Saved', 'プレビューはありません · 原稿は保存済みです'),
    '取消美术改版': ('Cancel Redesign', 'デザイン変更をキャンセル'),
    '取消局部微调': ('Cancel Local Adjustments', '部分調整をキャンセル'),
    '取消局部修复': ('Cancel Local Repair', '部分修復をキャンセル'),
    '本地模板降级 · {value0}': ('Local template fallback · {value0}', 'ローカルテンプレートで代替 · {value0}'),
    '网页主题 · {value0}': ('Web theme · {value0}', 'Web テーマ · {value0}'),
    '校验警告：{value0}\n{value1}': ('Validation warnings: {value0}\n{value1}', '検証の警告：{value0}\n{value1}'),
    '正在验证当前导出档案': ('Validating Current Export Archive', '現在の書き出しアーカイブを検証中'),
    '档案已导出：{value0} · 请求 {value1}': ('Archive exported: {value0} · Request {value1}', 'アーカイブを書き出しました：{value0} · リクエスト {value1}'),
    '候选方案已保存 · 准备视觉预览': ('Candidate saved · Preparing visual preview', '候補を保存しました · ビジュアルプレビューを準備中'),
    '候选方案已保存 · 正在编写主题代码': ('Candidate saved · Writing theme code', '候補を保存しました · テーマのコードを作成中'),
    '重试三个方向': ('Retry Three Directions', '3つの方向性を再試行'),
    '重试静态英雄帧': ('Retry Hero Frame', '代表フレームを再試行'),
    '生成所选方案': ('Generate Selected Design', '選択したデザインを生成'),
    '已采用并应用到当前字幕 · 拖动选框移动，拖动角点等比缩放 · Ctrl+Z 撤销': ('Adopted and applied to current subtitle · Drag the box to move, corners to scale proportionally · Ctrl+Z to undo', '現在の字幕に採用・適用しました · 選択枠をドラッグで移動、角をドラッグで比率を保持して拡大縮小 · Ctrl+Z で元に戻す'),
    '草稿已验证；当前字幕应用失败，可重试应用或导出当前草稿': ('Draft validated, but application failed. Retry applying or export the current draft.', '下書きの検証は完了しましたが、字幕への適用に失敗しました。再試行するか、現在の下書きを書き出せます。'),
    '{value0}\n可重试预览或复制诊断': ('{value0}\nRetry the preview or copy diagnostics', '{value0}\nプレビューを再試行するか、診断情報をコピーできます'),
    '当前主题尚未通过渲染校验，不能导出': ('This theme has not passed render validation and cannot be exported', '描画検証に合格していないため、このテーマは書き出せません'),
    '无法读取已保存成果：{value0}': ('Could not read saved results: {value0}', '保存済みの成果を読み込めませんでした：{value0}'),
    '无法继续草稿：{value0}': ('Could not resume draft: {value0}', '下書きを再開できませんでした：{value0}'),
    '其余方向已停止：{value0}；所选版本已保留': ('Other directions stopped: {value0}; the selected version is preserved', '他の方向性を停止しました：{value0}。選択したバージョンは保持されています'),
    '所选版本验证失败：{value0}；其他方向继续生成': ('Selected version failed validation: {value0}; other directions are still generating', '選択したバージョンの検証に失敗しました：{value0}。他の方向性は生成を続けています'),
    '调整字幕起点': ('Adjust Subtitle Start', '字幕の開始位置を調整'),
    '调整字幕终点': ('Adjust Subtitle End', '字幕の終了位置を調整'),
    '{value0} · 按住上下拖动调整轨道层级': ('{value0} · Drag vertically to reorder tracks', '{value0} · 上下にドラッグしてトラックの順序を変更'),
    '循环试听 {value0} - {value1}': ('Loop preview {value0} - {value1}', '繰り返し試聴 {value0} - {value1}'),
    '音画同步校正': ('Audio/Video Sync Correction', '音声・映像の同期補正'),
    '偏移毫秒数（正值：画面延后；负值：画面提前）。\n从当前播放头 {value0:.1f}s 起生效；输入 0 清除全部手动校正。\n已有校正：{value1}': ('Offset in milliseconds (positive: video later; negative: video earlier).\nApplies from the playhead at {value0:.1f}s. Enter 0 to clear all manual corrections.\nExisting corrections: {value1}', 'オフセットをミリ秒で入力（正：映像を遅らせる、負：映像を早める）。\n現在の再生位置 {value0:.1f}秒から適用します。0 で全ての手動補正を解除します。\n既存の補正：{value1}'),
    '重命名视频轨': ('Rename Video Track', '映像トラック名を変更'),
    '轨道名称': ('Track Name', 'トラック名'),
    'Solo / 独听：{value0}{value1}': ('Solo: {value0}{value1}', 'Solo：{value0}{value1}'),
    '动画预览失败：{value0}\n可关闭后重试；原主题保留': ('Animation preview failed: {value0}\nClose and retry; the original theme is preserved', 'アニメーションのプレビューに失敗しました：{value0}\n閉じて再試行できます。元のテーマは保持されています'),
    '导入 .2byte-theme 档案': ('Import .2byte-theme Archive', '.2byte-theme アーカイブを読み込む'),
    '重命名样式': ('Rename Style', 'スタイル名を変更'),
    '删除样式': ('Delete Style', 'スタイルを削除'),
    '确定隐藏这个内置样式？之后可用“恢复内置”找回。': ('Hide this built-in style? You can bring it back with “Restore Built-ins”.', 'この内蔵スタイルを非表示にしますか？「内蔵を復元」で再表示できます。'),
    '确定删除这个自定义样式？': ('Delete this custom style?', 'このカスタムスタイルを削除しますか？'),
    '删除选中样式': ('Delete Selected Styles', '選択したスタイルを削除'),
    '确定删除选中的 {value0} 个样式？内置样式不会受影响。': ('Delete the {value0} selected styles? Built-in styles are unaffected.', '選択した {value0}件のスタイルを削除しますか？内蔵スタイルには影響しません。'),
    '删除全部 AI 样式': ('Delete All AI Styles', '全ての AI スタイルを削除'),
    '确定删除全部未收藏的 AI 样式？': ('Delete all AI styles that are not favorites?', 'お気に入り以外の AI スタイルを全て削除しますか？'),
    '确定删除全部 AI 样式（包括收藏）？': ('Delete all AI styles, including favorites?', 'お気に入りも含め、全ての AI スタイルを削除しますか？'),
    '当前没有被隐藏的内置预设。': ('No Built-in Presets Are Hidden', '非表示の内蔵プリセットはありません'),
    '请先选择一个或多个样式。': ('Select one or more styles first.', '先にスタイルを選択してください。'),
    '{value0} · 完整动画': ('{value0} · Full Animation', '{value0} · アニメーション全体'),
    '{value0} · 字幕本体': ('{value0} · Subtitle Only', '{value0} · 字幕のみ'),
    '字幕视觉方向 · {value0} 候选 · {value1} 就绪{value2}': ('Subtitle Design · Candidates: {value0} · Ready: {value1}{value2}', '字幕デザイン · 候補 {value0} · 準備完了 {value1}{value2}'),
    '完整演示 {value0:g}s · 实际采用保持原字幕时长 · {value1}': ('Full demo {value0:g}s · Applied subtitles keep their original duration · {value1}', 'デモ全体 {value0:g}秒 · 適用時は元の字幕の長さを保持 · {value1}'),
    '仅静态预览，动画未完成': ('Static Preview Only · Animation Incomplete', '静止画プレビューのみ · アニメーションは未完成です'),
    '背景仅用于观看，不进入透明导出': ('Background is for viewing only and is excluded from transparent exports', '背景は確認用です。透過書き出しには含みません'),
    '旧预览未提供透明序列，保留原预渲染背景': ('This older preview has no transparent sequence; its rendered background is retained', '旧プレビューには透過連番がないため、レンダリング済みの背景を保持します'),
    '{value0} · 自动循环；也可点击作品': ('{value0} · Loops automatically; you can also click the artwork', '{value0} · 自動ループ（作品のクリックも可能）'),
    '完整画面 · {value0:g} 秒循环 · 实际画面占比': ('Full Frame · {value0:g}s loop · Actual scale in video', '画面全体 · {value0:g}秒ループ · 動画内の実際の比率'),
    '返回字幕本体': ('Back to Subtitle Only', '字幕のみの表示に戻る'),
    '查看视频叠加': ('View Video Overlay', '動画への重ね合わせを表示'),
    '查看完整画面占比': ('View Full Frame Scale', '画面全体での比率を表示'),
    '正在处理此方向': ('Processing This Direction', 'この方向性を処理中'),
    '预览尚未就绪\n{value0}': ('Preview Not Ready\n{value0}', 'プレビューの準備中\n{value0}'),
    '本地精修未应用，原稿保留：{value0}': ('Local polish was not applied; original preserved: {value0}', 'ローカルでの仕上げは適用されませんでした。原稿を保持しています：{value0}'),
    '运行中{value0}': ('Running{value0}', '実行中{value0}'),
    '已配置：{value0}': ('Configured: {value0}', '設定済み：{value0}'),
    '默认模型': ('Default Model', '既定のモデル'),
    '打开 Google 登录': ('Open Google Sign-In', 'Google ログインを開く'),
    'Antigravity CLI Session：未知': ('Antigravity CLI Session: Unknown', 'Antigravity CLI セッション：不明'),
    '{value0} Session：未知': ('{value0} Session: Unknown', '{value0} セッション：不明'),
    'Antigravity CLI Session：检测真实请求中…': ('Antigravity CLI Session: Testing a real request…', 'Antigravity CLI セッション：実際のリクエストを確認中…'),
    '{value0} Session：检测中…': ('{value0} Session: Checking…', '{value0} セッション：確認中…'),
    'CLI：已安装': ('CLI: Installed', 'CLI：インストール済み'),
    'CLI：未检测到': ('CLI: Not Detected', 'CLI：未検出'),
    '{value0}：未知': ('{value0}: Unknown', '{value0}：不明'),
    '{value0}：未登录或不可调用': ('{value0}: Not signed in or unavailable', '{value0}：未ログインまたは利用不可'),
    '正在启动官方登录窗口…': ('Opening the official sign-in window…', '公式ログイン画面を開いています…'),
    '正在退出官方 CLI 登录…': ('Signing out of the official CLI…', '公式 CLI からログアウト中…'),
    '打开登录': ('Open Sign-In', 'ログインを開く'),
    '安装 {value0}': ('Install {value0}', '{value0}をインストール'),
    '当前未由 2ByteASR 自动安装 {value0}。请从该服务的官方发布渠道安装，完成后回到这里点击“检测 CLI”。\n\n2ByteASR 不读取或保存 OAuth token。': ("2ByteASR does not currently install {value0} automatically. Install it from the service's official distribution channel, then return here and choose “Check CLI”.\n\n2ByteASR does not read or store OAuth tokens.", '現在、2ByteASR は {value0}を自動でインストールしません。サービスの公式配布元からインストールし、ここに戻って「CLI を確認」を選択してください。\n\n2ByteASR は OAuth トークンを読み取り・保存しません。'),
    '预计模型下载约 {value0:.1f} GB。{value1}': ('Estimated model download: {value0:.1f} GB. {value1}', 'モデルのダウンロード予定：約 {value0:.1f} GB。{value1}'),
    '松开鼠标即可放入 {value0} 个可用文件': ('Release to add {value0} supported files', 'ドロップして対応ファイル {value0}件を追加'),
    '松开鼠标即可添加这个视频或音频': ('Release to add this video or audio file', 'ドロップしてこの動画・音声を追加'),
    '发现新版本': ('Update Available', '新しいバージョンがあります'),
    '发现 2ByteASR {value0}（当前 {value1}）。\n\n是否下载小型更新包？下载完成后程序会退出、覆盖程序文件并自动重新打开；不会重新下载模型或 Python 环境。': ('2ByteASR {value0} is available (current: {value1}).\n\nDownload the small update package? After downloading, the app will exit, replace its files and restart. Models and Python environments will not be downloaded again.', '2ByteASR {value0}が利用できます（現在：{value1}）。\n\n差分更新をダウンロードしますか？完了後、アプリを終了してファイルを更新し、自動で再起動します。モデルや Python 環境は再ダウンロードしません。'),
    '更新下载失败': ('Update Download Failed', '更新のダウンロードに失敗しました'),
    '更新未修改任何程序文件。可稍后重试或直接覆盖安装新版。\n\n{value0}': ('No application files were changed. Retry later or install the new version over this one.\n\n{value0}', 'アプリのファイルは変更されていません。後で再試行するか、新版を上書きインストールしてください。\n\n{value0}'),
    '已保存（···{value0}，留空保持）': ('Saved (···{value0}; leave blank to keep)', '保存済み（···{value0}、空欄で保持）'),
    '请输入当前 ASR 服务的 API Key': ('Enter the API key for the current ASR service', '現在の ASR サービスの API キーを入力'),
    '新建方案': ('New Plan', 'プランを新規作成'),
    '方案名称：': ('Plan name:', 'プラン名：'),
    '另存为方案': ('Save As Plan', '別のプランとして保存'),
    '新方案名称：': ('New plan name:', '新しいプラン名：'),
    '重命名方案': ('Rename Plan', 'プラン名を変更'),
    '删除方案': ('Delete Plan', 'プランを削除'),
    '删除“{value0}”？模型文件不会被删除。': ('Delete “{value0}”? Model files will not be deleted.', '「{value0}」を削除しますか？モデルファイルは削除しません。'),
    '{value0} · 预计显存约 {value1:.1f} GB。{value2}': ('{value0} · Estimated GPU memory: {value1:.1f} GB. {value2}', '{value0} · GPU メモリの目安：約 {value1:.1f} GB。{value2}'),
    '请输入 DashScope API Key': ('Enter DashScope API Key', 'DashScope API キーを入力'),
    '当前组合中的以下组件需要 CUDA：\n{value0}': ('These components in the current configuration require CUDA:\n{value0}', '現在の構成で次のコンポーネントは CUDA が必要です：\n{value0}'),
    '重试未完成校对': ('Retry Unfinished Review', '未完了の確認を再試行'),
    '在浏览器完成登录即可（窗口会自动收尾，无需保持任何外部窗口）：<br>{value0}': ('Finish signing in in your browser. The window closes automatically; no external window needs to stay open:<br>{value0}', 'ブラウザーでログインしてください。完了後は自動で終了するため、外部ウィンドウを開いたままにする必要はありません：<br>{value0}'),
    '无法开始识别': ('Cannot Start Recognition', '認識を開始できません'),
    '当前工程或媒体文件已经移动，请在 Studio 中重新关联后再试。': ('The project or media file has moved. Relink it in Studio and try again.', 'プロジェクトまたは素材ファイルが移動されています。Studio で再リンクしてから再試行してください。'),
    '无法配置 API': ('Cannot Configure API', 'API を設定できません'),
    '未知的 ASR API 预设：{value0}': ('Unknown ASR API preset: {value0}', '不明な ASR API プリセット：{value0}'),
    '无法切换模型': ('Cannot Switch Model', 'モデルを切り替えられません'),
    '不支持的识别后端：{value0} / {value1}': ('Unsupported recognition backend: {value0} / {value1}', '未対応の認識バックエンド：{value0} / {value1}'),
    '已经是最新版': ('Already Up to Date', '最新版です'),
    '当前版本 {value0}，发布版 {value1}。': ('Current version: {value0}; released version: {value1}.', '現在のバージョン：{value0}、公開版：{value1}。'),
    '发现 2ByteASR {value0}。这个旧版尚不支持一键增量更新，可以下载新版安装包直接覆盖安装；模型、环境和设置都会保留。\n\n现在打开下载页吗？': ('2ByteASR {value0} is available. This older version does not support incremental updates. Install the new package over it; models, environments and settings will be preserved.\n\nOpen the download page now?', '2ByteASR {value0}が利用できます。この旧版は差分更新に対応していません。新版を上書きインストールできます。モデル・環境・設定は保持されます。\n\nダウンロードページを開きますか？'),
    '素材正在处理中': ('Media Is Being Processed', '素材を処理中です'),
    '该素材正在处理中，停止该素材任务后移除？': ('This media is being processed. Stop its task and remove it?', 'この素材は処理中です。タスクを停止して除去しますか？'),
    '请先结束当前识别任务，再清空素材。': ('Finish the current recognition task before clearing media.', '現在の認識タスクを終了してから素材を消去してください。'),
    '当前任务正在处理，请结束后再重新选择素材。': ('A task is running. Finish it before choosing media again.', 'タスクを実行中です。終了してから素材を選び直してください。'),
    '修复未完成，原环境已保留。\n\n{value0}': ('Repair incomplete. The original environment is preserved.\n\n{value0}', '修復は完了していません。元の環境は保持されています。\n\n{value0}'),
    '本地模型运行库需要修复': ('Local Model Runtime Needs Repair', 'ローカルモデルの実行環境に修復が必要です'),
    '{value0}\n\n{value1}\n\n请打开模型工坊，选择当前模型并点击“校验并修复”。': ('{value0}\n\n{value1}\n\nOpen Model Workshop, select the current model and choose “Verify and Repair”.', '{value0}\n\n{value1}\n\nモデル工房を開き、現在のモデルを選んで「検証と修復」を実行してください。'),
    '选择已有字幕任务报告': ('Choose an Existing Subtitle Task Report', '既存の字幕タスクレポートを選択'),
    '工程保存失败': ('Project Save Failed', 'プロジェクトの保存に失敗しました'),
    '无法启动更新': ('Cannot Start Update', '更新を開始できません'),
    '术语增强说明': ('About Term Boost', '用語補正について'),
    '术语增强会把本批启用的词库和已确认专名作为识别参考。\n\n本地图鉴只提供弱候选，不会仅凭名字相似强制改字；联网复核时再结合上下文确认专名。\n\n游戏、PVP 或专名密集的内容建议开启；通用闲聊可关闭。': ('Term Boost uses enabled libraries and confirmed proper names as recognition references.\n\nLocal references supply weak candidates; name similarity alone never forces replacements. Online review also checks context.\n\nRecommended for games, PVP and content with many proper names; optional for general conversation.', '用語補正は、有効な用語集と確認済みの固有名詞を認識の参考にします。\n\nローカル資料は参考候補のみを提供し、名前が似ているだけで置き換えることはありません。オンライン確認では文脈も考慮します。\n\nゲーム・PVP・固有名詞が多い内容では有効を推奨します。一般的な雑談では無効にできます。'),
    '无法新建方案': ('Cannot Create Plan', 'プランを作成できません'),
    '无法另存方案': ('Cannot Save Plan As', '別のプランとして保存できません'),
    '无法重命名': ('Cannot Rename', '名前を変更できません'),
    '术语增强 ON\n已绑定：{value0}': ('Term Boost ON\nLinked: {value0}', '用語補正 ON\n連携済み：{value0}'),
    '修复后重新检查仍未通过。\n\n{value0}': ('The post-repair check still failed.\n\n{value0}', '修復後の再検証にも合格しませんでした。\n\n{value0}'),
    '恢复未完成': ('Recovery Incomplete', '復元は未完了です'),
    '{value0}\n原工程及字幕输出保持不变。': ('{value0}\nOriginal project and subtitle outputs are unchanged.', '{value0}\n元のプロジェクトと字幕出力は変更されていません。'),
    '说话人方案保存失败：{value0}': ('Could not save speaker plan: {value0}', '話者プランを保存できませんでした：{value0}'),
    '识别后端未保存': ('Recognition Backend Not Saved', '認識バックエンドが保存されていません'),
})

# Runtime and terminology review
STRINGS.update({
    '最小化': ('Minimize', '最小化'),
    '最大化': ('Maximize', '最大化'),
    '速度': ('Speed', '速度'),
    '使用': ('Use', '使用'),
    '；速度：': ('; Speed: ', '、速度：'),
    '警告 / Error': ('Warnings / errors', '警告・エラー'),
    '操作': ('Actions', '操作'),
    '人物': ('Person', '人物'),
    '事件': ('Event', '出来事'),
    '保存': ('Save', '保存'),
    '返回兔白字幕工程库': ('Back to Subtitle Studio Library', '字幕スタジオのライブラリに戻る'),
    '分析方式': ('Analysis mode', '分析方法'),
    '分析': ('Analyze', '分析'),
    '洛克王国：世界': ('Roco Kingdom: World', 'Roco Kingdom: World'),
    '文本': ('Text', 'テキスト'),
    '说话人 {number}': ('Speaker {number}', '話者 {number}'),
    '统一字幕': ('Combined Subtitles', '統合字幕'),
    '游戏背景声': ('Game Audio', 'ゲーム音声'),
    '声音诊断': ('Audio Check', '音声診断'),
    '适应窗口': ('Fit', '全体表示'),
    'AI 断句': ('AI Split', 'AI 文分割'),
    '关于': ('About', 'このアプリについて'),
    'Speaker Manager': ('Speaker Management', '話者管理'),
    '完整工具 / 默认工作区': ('Full tools / default workspace', '全ツール・既定のワークスペース'),
    '封面精简工作区': ('Compact cover workspace', '表紙用の簡易ワークスペース'),
    '未保存修改': ('Unsaved changes', '未保存の変更'),
    '文档已保存': ('Document saved', '保存済み'),
    '无源媒体': ('No source media', '元の素材なし'),
    '计算中': ('Calculating', '計算中'),
    '原生 JSON Schema': ('Native JSON Schema', 'ネイティブ JSON Schema'),
    'CLI 能力待检测': ('CLI capabilities not checked', 'CLI の機能は未確認'),
    '结构化输出': ('Structured output', '構造化出力'),
    '文字上下文': ('Text context', 'テキストの文脈'),
    '当前模型支持图片': ('This model supports images', 'このモデルは画像に対応'),
    '图片能力待模型目录确认 · 文字上下文': ('Image support unconfirmed · Text context', '画像対応は未確認 · テキストの文脈'),
    '匿名标签均待确认，不按编号或发言量认定主播。': ('Anonymous labels require confirmation; numbers and speaking time do not identify the streamer.', '匿名ラベルは全て確認が必要です。番号や発話量だけで配信者とは判断しません。'),
    '超过10条去重原始发言才默认作为主要候选；其余收进游戏背景声，保留原文与标签。': ('Only speakers with more than 10 distinct original utterances become main candidates by default. The rest are grouped as game audio, preserving text and labels.', '重複を除いた元の発話が10件を超える話者を主要候補とします。その他は元の文字とラベルを保持してゲーム音声にまとめます。'),
    '全部候选已分类。': ('All candidates classified.', '全候補を分類しました。'),
    '有未应用修改。': ('Unapplied changes. ', '未適用の変更があります。'),
    '未返回可读原因': ('No readable reason was returned', '読み取れる理由が返されませんでした'),
})

# Secondary surface review
STRINGS.update({
    '选择要导出的说话人。时间位置与空白均保留。': ('Choose speakers to export. Timing and gaps are preserved.', '書き出す話者を選択してください。時刻と空白は保持されます。'),
    '全部说话人': ('All Speakers', '全ての話者'),
    'PNG · 保留透明区域': ('PNG · Keep transparency', 'PNG · 透過部分を保持'),
    'JPEG · 合成背景色': ('JPEG · Flatten onto background', 'JPEG · 背景色と合成'),
    '全部模板': ('All Templates', '全てのテンプレート'),
    '还没有模板。编辑封面后点击“保存为模板”，即可保留所有图层和位置。': ('No templates yet. Edit a cover and choose “Save as Template” to preserve all layers and positions.', 'テンプレートはまだありません。表紙を編集して「テンプレートとして保存」を選ぶと、全レイヤーと位置を保存できます。'),
    '还没有模板。编辑封面后选择“保存为模板”，也可导入 XCF / PSD。': ('No templates yet. Edit a cover and choose “Save as Template”, or import an XCF / PSD file.', 'テンプレートはまだありません。表紙を編集して「テンプレートとして保存」を選ぶか、XCF / PSD を読み込んでください。'),
    '完整性未知': ('Integrity unknown', '完全性は未確認'),
    '还没有联网更新记录。': ('No online update history yet.', 'オンライン更新の履歴はまだありません。'),
    '提示词已复制。将 AI 返回的 TSV 粘贴到此处后解析预览。': ('Prompt copied. Paste the TSV returned by AI here, then parse and preview it.', 'プロンプトをコピーしました。AI が返した TSV をここに貼り付け、解析してプレビューしてください。'),
    '没有提取到候选词。请换一个来源或粘贴更多资料。': ('No candidate terms extracted. Try another source or paste more reference material.', '候補の用語を抽出できませんでした。別の情報源を選ぶか、資料を追加してください。'),
    '请先粘贴资料文本。': ('Paste reference text first.', '先に資料の文章を貼り付けてください。'),
    '请先输入网页 URL。': ('Enter a webpage URL first.', '先に Web ページの URL を入力してください。'),
    '待复核项': ('Items to Review', '要確認の項目'),
    '径向渐变': ('Radial Gradient', '放射状グラデーション'),
    '等待补充事件摘要': ('Waiting for an event summary', 'イベントの要約を待機中'),
    '音轨': ('Audio Track', '音声トラック'),
    '查看工程': ('View Project', 'プロジェクトを表示'),
    '内置': ('Built-in', '内蔵'),
    '恢复声音': ('Unmute', 'ミュートを解除'),
    '静音轨道': ('Mute Track', 'トラックをミュート'),
    '取消 Solo': ('Disable Solo', 'Solo を解除'),
    'Solo / 独听此轨': ('Solo This Track', 'このトラックを Solo 再生'),
    '完整候选并发：': ('Concurrent full candidates:', '完全候補の同時生成数：'),
    '完整演示': ('Full Demo', '全体デモ'),
    '仅入场': ('Entrance Only', '登場のみ'),
    '仅退场': ('Exit Only', '退場のみ'),
    '阅读段': ('Reading Section', '読む区間'),
    '深色底': ('Dark Background', '暗い背景'),
    '浅色底': ('Light Background', '明るい背景'),
    '棋盘底': ('Checkerboard', '市松模様'),
    '仅用于全文断句。': ('Used only for full-text segmentation.', '全文の文分割にのみ使用します。'),
    '请关闭 2ByteASR 后从配置器点击“重新检查”。': ('Close 2ByteASR, then choose “Check Again” in the configurator.', '2ByteASR を閉じてから、設定ツールで「再確認」を選択してください。'),
    '未能确定具体失败模块。': ('The failing module could not be identified.', '失敗したモジュールを特定できませんでした。'),
    '完整建库': ('Build Full Library', '用語集を全体作成'),
    '更新': ('Update', '更新'),
    ' 已隐藏': (' hidden', ' 非表示'),
    '无需下载': ('No download needed', 'ダウンロード不要'),
    '版本不匹配': ('Version mismatch', 'バージョン不一致'),
    '图片': ('Image', '画像'),
    ' · 已缓存': (' · Cached', ' · キャッシュ済み'),
    ' · {seconds} 秒无新进度': (' · No progress for {seconds}s', ' · {seconds}秒間進捗なし'),
    '未确认候选：{names}（保留待确认，不阻止应用）。': ('Unconfirmed candidates: {names} (kept pending; application is allowed).', '未確認の候補：{names}（確認待ちのまま保持します。適用は可能です）。'),
    '当前选择。': ('Current selection. ', '現在の選択。'),
    '未发现': ('None found', 'なし'),
    '未进行视觉模型复核': ('No visual model review performed', '視覚モデルによる確認は未実施'),
    ' · 当前无可用声音，请检查脱机、静音或片段范围': (' · No audio available; check offline media, mute and clip ranges', ' · 使用可能な音声がありません。オフラインの素材、ミュート、クリップの範囲を確認してください'),
    ' · Mute优先': (' · Mute takes priority', ' · ミュートを優先'),
    '适配作品大小': ('Fit Artwork', '作品に合わせる'),
    '真实画面占比': ('Actual Video Scale', '動画内の実際の比率'),
    '推荐用于中文长视频与多人内容。': ('Recommended for long Chinese videos and multiple speakers.', '長い中国語動画や複数話者のコンテンツに推奨します。'),
    ' 当前素材更推荐：{name}': (' Recommended for this media: {name}', ' この素材への推奨：{name}'),
    '准备工程': ('Preparing Project', 'プロジェクトを準備中'),
    '视频轨合成': ('Compositing Video Tracks', '映像トラックを合成中'),
    '准备字幕': ('Preparing Subtitles', '字幕を準備中'),
    '高级样式渲染': ('Rendering Advanced Styles', '高度なスタイルを描画中'),
    '视频编码': ('Encoding Video', '動画をエンコード中'),
    '封装文件': ('Finalizing File', 'ファイルを仕上げ中'),
    '当前步骤：{label}。编码尚未开始，因此不显示 0% 进度。': ('Current step: {label}. Encoding has not started yet.', '現在の処理：{label}。エンコードはまだ開始していません。'),
    '识别中 · {stage} · {minutes:02d}:{seconds:02d}': ('Transcribing · {stage} · {minutes:02d}:{seconds:02d}', '認識中 · {stage} · {minutes:02d}:{seconds:02d}'),
    '任务结束': ('Task Finished', 'タスク終了'),
    '任务结束，有失败项': ('Task Finished with Failures', 'タスク終了・失敗あり'),
})

# Opened native dialogs, controls and menus
STRINGS.update({
    '命令': ('Command', 'コマンド'),
    '当前快捷键': ('Shortcut', 'ショートカット'),
    '播放 / 暂停': ('Play / Pause', '再生／一時停止'),
    '轨道音量（分贝）': ('Track Volume (dB)', 'トラック音量（dB）'),
    '选择工具': ('Selection Tool', '選択ツール'),
    '剃刀工具（按住拖动选切分点）': ('Razor Tool (drag to choose a cut)', 'レーザーツール（ドラッグで切断位置を指定）'),
    '在播放头分割所有未锁视频轨': ('Split Unlocked Video Tracks at Playhead', '再生ヘッド位置で未ロックの全映像トラックを分割'),
    '合并工具（点选字幕后拖动方向合并）': ('Merge Tool (select subtitle and drag)', '結合ツール（字幕を選択して方向をドラッグ）'),
    '波纹向前合并（与上一条合并）': ('Ripple Merge with Previous Subtitle', '前の字幕とリップル結合'),
    '波纹向后合并（与下一条合并）': ('Ripple Merge with Next Subtitle', '次の字幕とリップル結合'),
    '字幕起点至播放头 / 视频向前波纹剪除': ('Set Subtitle Start / Ripple Trim Video Before Playhead', '字幕の開始を再生ヘッドへ／前方の映像をリップル削除'),
    '字幕终点至播放头 / 视频向后波纹剪除': ('Set Subtitle End / Ripple Trim Video After Playhead', '字幕の終了を再生ヘッドへ／後方の映像をリップル削除'),
    '重做': ('Redo', 'やり直す'),
    '重做（备用）': ('Redo (Alternative)', 'やり直す（予備）'),
    '保存工程': ('Save Project', 'プロジェクトを保存'),
    '上一帧': ('Previous Frame', '前のフレーム'),
    '下一帧': ('Next Frame', '次のフレーム'),
    '上一条字幕': ('Previous Subtitle', '前の字幕'),
    '下一条字幕': ('Next Subtitle', '次の字幕'),
    '反向播放': ('Play Backward', '逆再生'),
    '暂停': ('Pause', '一時停止'),
    '正向播放': ('Play Forward', '順再生'),
    '切换时间轴吸附': ('Toggle Timeline Snapping', 'タイムラインのスナップを切替'),
    '确认当前审核': ('Confirm Current Review', '現在の字幕を確認済みにする'),
    '确认并播放下一条审核': ('Confirm and Play Next Review', '確認して次の字幕を再生'),
    '进入 / 退出审核模式': ('Toggle Review Mode', '確認モードを切替'),
    '重新识别当前审核': ('Transcribe Current Review Again', '確認中の字幕を再認識'),
    '手动编辑当前审核': ('Edit Current Review', '確認中の字幕を手動編集'),
    '跳过当前审核': ('Skip Current Review', '確認中の字幕をスキップ'),
    '退出优先审核': ('Exit Priority Review', '優先確認を終了'),
    '添加字幕': ('Add Subtitle', '字幕を追加'),
    '批量替换字幕文字': ('Batch Replace Subtitle Text', '字幕の文字を一括置換'),
    '将 I/O 加入剪辑候选': ('Add In/Out Range to Clip Candidates', '入出点の範囲を切り抜き候補に追加'),
    '候选恢复': ('Candidate Recovery', '候補を復元'),
    '工程未保存原始 MOSS 候选，且任务报告没有缓存路径。请选择本素材的 MOSS 缓存目录。': ('This project has no original MOSS candidates or recorded cache path. Choose the MOSS cache folder for this media.', '元の MOSS 候補とキャッシュのパスがプロジェクト・レポートにありません。この素材の MOSS キャッシュフォルダーを選択してください。'),
    '← 返回兔白字幕': ('← Back to Subtitle Studio', '← 字幕スタジオに戻る'),
    '源帧率': ('Source Frame Rate', '元のフレームレート'),
    '与源媒体同目录': ('Source Media Folder', '元の素材と同じフォルダー'),
    '两者': ('Both', '両方'),
    '体积优先': ('Smaller File', 'ファイルサイズ優先'),
    '入点到出点': ('In to Out', '入点から出点'),
    '分别导出': ('Export Separately', '個別に書き出す'),
    '前缀，可留空': ('Prefix (optional)', '接頭辞（省略可）'),
    '合并': ('Combine', '結合'),
    '后缀，可留空': ('Suffix (optional)', '接尾辞（省略可）'),
    '工程 exports': ('Project exports Folder', 'プロジェクトの exports フォルダー'),
    '整个视频': ('Entire Video', '動画全体'),
    '无音频': ('No Audio', '音声なし'),
    '极高质量': ('Very High Quality', '最高画質'),
    '自定义位置': ('Custom Location', '場所を指定'),
    '直接复制': ('Copy Stream', 'ストリームをコピー'),
    '推荐：适合普通上传': ('Recommended for regular uploads', '通常のアップロードに推奨'),
    '高质量：更高码率，文件较大': ('High quality: higher bitrate and larger files', '高画質：ビットレートが高く、ファイルも大きくなります'),
    '极高质量：适合存档': ('Very high quality: suitable for archiving', '最高画質：保存用に適しています'),
    '体积优先：更小文件': ('Smaller output files', '出力ファイルを小さくします'),
    '自定义：使用高级参数': ('Custom: use advanced parameters', 'カスタム：詳細パラメーターを使用'),
    '正在准备 Native ASS 字幕烧录…': ('Preparing native ASS subtitle burn-in…', 'ネイティブ ASS 字幕の焼き込みを準備中…'),
    '正在初始化编码器…': ('Initializing encoder…', 'エンコーダーを初期化中…'),
    '校验完整视频与音频后发布文件…': ('Validating the full video and audio before publishing the file…', 'ファイルの確定前に動画全体と音声を検証中…'),
    '封装完成': ('File Finalized', 'ファイルの仕上げ完了'),
    '正在解析工程并检查输入文件…': ('Reading the project and checking input files…', 'プロジェクトを解析し、入力ファイルを確認中…'),
    '完整候选并发：{count}': ('Concurrent full candidates: {count}', '完全候補の同時生成数：{count}'),
    '未配置': ('Not configured', '未設定'),
    '先生成1个完整候选': ('Generate One Full Candidate First', 'まず完全な候補を1つ生成'),
    '比较3个组件草案（一次设计请求）': ('Compare Three Component Drafts (One Request)', '3つの構成案を比較（リクエスト1回）'),
    '生成3个完整候选': ('Generate Three Full Candidates', '完全な候補を3つ生成'),
    '应用到当前字幕': ('Apply to Current Subtitle', '現在の字幕に適用'),
    '请先在时间轴选中字幕，再应用已采用的方案': ('Select a subtitle on the timeline, then apply the adopted design', 'タイムラインで字幕を選択してから、採用したデザインを適用してください'),
    '全部分类': ('All Categories', '全てのカテゴリ'),
    '全部状态': ('All Statuses', '全ての状態'),
    '主播 / 创作者': ('Streamer / Creator', '配信者・クリエイター'),
    '其他': ('Other', 'その他'),
    '参考': ('Reference', '参考'),
    '已隐藏': ('Hidden', '非表示'),
    '技能': ('Ability', 'スキル'),
    '活动 / 嘉年华': ('Event / Festival', 'イベント・フェス'),
    '游戏术语': ('Game Terms', 'ゲーム用語'),
    '系列 / IP': ('Series / IP', 'シリーズ・IP'),
})

# Model descriptions and published evidence; identifiers and values remain unchanged.
STRINGS.update({'在 2ByteASR 中先生成完整文字骨架、说话人标签和片段时间信息；FireRed 再细化字词边界，Qwen3-ASR 再提供独立文字证据。': ('Builds the complete transcript, speaker labels and segment timing before the timeline and text-review stages add independent evidence.', '2ByteASRでは、まず全文の骨格、話者ラベル、区間の時刻を生成します。続いてFireRedが文字・単語の境界を精密化し、Qwen3-ASRが独立した文字起こし結果を提供します。'), 'Whisper-Medium 音频编码器提取 16 kHz、80 维 mel 特征，经 4 倍时间合并和 MLP 适配器送入 Qwen3-0.6B 风格因果解码器；模型以单条序列联合生成时间戳、说话人标签、正文和可选声学事件。': ('A Whisper-Medium audio encoder feeds a Qwen3-0.6B-style causal decoder through temporal merging and an MLP adaptor, jointly emitting timestamps, speaker labels, text and optional acoustic events.', 'Whisper-Mediumエンコーダーが16 kHz音声から80次元のmel特徴を抽出し、時間方向の4倍結合とMLPアダプターを経てQwen3-0.6B型の因果デコーダーに渡します。時刻、話者ラベル、本文、任意の音響イベントを単一系列で生成します。'), '先保留完整语义，再向后续时间轴与文字复核提供稳定骨架。': ('Preserves long-form meaning and a stable speaker-aware backbone.', '全文の意味を保持し、後続の時刻調整とテキスト確認に安定した骨格を提供します。'), '需要 NVIDIA CUDA；说话人标签是区分依据，不等同于自动识别真实姓名。': ('Requires NVIDIA CUDA. Speaker labels distinguish voices but do not identify real names.', 'NVIDIA CUDAが必要です。話者ラベルは話者を区別するもので、実名を自動特定するものではありません。'), '输入本地音频；输出初稿文本、分段和说话人证据。': ('Input: local audio. Output: draft text, segments and speaker evidence.', 'ローカル音声を入力し、下書きテキスト、区間、話者情報を出力します。'), '2ByteASR 内置 MOSS 转写与说话人工作进程。': ("2ByteASR's bundled MOSS transcription and speaker worker.", '2ByteASR内蔵のMOSS文字起こし・話者処理ワーカー。'), '0.9B（端到端长音频多说话人模型）': ('0.9B (end-to-end long-form multi-speaker)', '0.9B（長時間音声・複数話者向けエンドツーエンドモデル）'), '官方仅公布 50+ 语言摘要': ('Official 50+ language summary', '公式情報では50以上の言語に対応と記載'), '官方未逐项公开完整语言或方言清单': ('The official project does not enumerate the full language or dialect list', '言語・方言の完全な一覧は公式未公開'), '长音频、多说话人、会议/播客/视频': ('Long-form, multi-speaker meetings, podcasts and video', '長時間音声、複数話者、会議・ポッドキャスト・動画'), '官方未单列': ('Not stated', '公式に個別の記載なし'), '长音频': ('7 dialects', '長時間音声'), '时间戳': ('Timestamps', 'タイムスタンプ'), '事件感知': ('Acoustic events', '音響イベント検出'), 'MOSS Transcribe Diarize 0.9B；长音频多说话人客观评测': ('Official checkpoint evaluation; see the source for the exact setup.', 'MOSS Transcribe Diarize 0.9B：長時間・複数話者音声の客観評価'), '准确度表未声明硬件': ('Not stated in directly comparable form', '精度表にハードウェアの記載なし'), '越低越好': ('Lower is better', '低いほど良い'), '官方 README（仓库 2026-08-15 状态）': ('Official source reviewed 2026-09-18', '公式README（2026-08-15時点のリポジトリ）'), '官方未声明': ('See official source', '公式に記載なし'), '拼接后最小排列字符错误率；MOSS 0.9B': ('Official checkpoint evaluation; see the source for the exact setup.', '連結後の最小話者順列に基づく文字誤り率（MOSS 0.9B）'), 'SGLang Omni；concurrency=1；长序列多说话人 ASR': ('Official checkpoint evaluation; see the source for the exact setup.', 'SGLang Omni、concurrency=1、長系列・複数話者ASR'), '单张 NVIDIA H100': ('One NVIDIA H100', 'NVIDIA H100 1枚'), '官方 README（仓库 2026-08-16 状态）': ('Official source reviewed 2026-09-18', '公式README（2026-08-16時点のリポジトリ）'), '官方 SGLang Omni 吞吐表使用单张 H100；上方准确度表未声明硬件。2ByteASR 本地路径使用 NVIDIA CUDA。': ('Official accuracy tables cover long-form multi-speaker sets; the published SGLang Omni speed result uses one H100.', '公式のSGLang Omniスループット表はH100 1枚を使用。上の精度表にはハードウェアの記載がありません。2ByteASRのローカル実行にはNVIDIA CUDAを使用します。'), '官方推荐 Python 3.12 + Transformers 5.x；SGLang Omni 面向 CUDA 13，vLLM 同时给出 CUDA 12/13 路径。2ByteASR 使用独立 MOSS 环境。': ('The official project recommends Python 3.12 and Transformers 5.x. 2ByteASR uses its existing isolated MOSS environment.', '公式推奨はPython 3.12とTransformers 5.xです。SGLang OmniはCUDA 13向け、vLLMにはCUDA 12/13の手順があります。2ByteASRは独立したMOSS環境を使用します。'), '中文长音频 + 说话人区分，适合作为第一遍主力转写保留完整语义骨架。': ('Preserves long-form meaning and a stable speaker-aware backbone.', '中国語の長時間音声と話者分離に対応。最初の主文字起こしで全文の意味を保持する用途に適しています。'), '中文/方言语音识别与细粒度时间轴。': ('Chinese and dialect recognition with fine-grained subtitle timing.', '中国語・方言の音声認識と細かな時刻調整。'), '在 2ByteASR 中接收 MOSS 已保留的语义骨架，提供独立文字结果、字词级时间戳和置信度，主要用于第二阶段时间边界。': ('Adds independent text, word timestamps and confidence after the MOSS backbone, primarily for second-stage subtitle boundaries.', '2ByteASRではMOSSが保持したテキストの骨格を受け取り、独立した文字起こし、文字・単語の時刻、信頼度を提供します。主に第2段階の時刻境界に使用します。'), 'FireRedASR2-AED 采用 Attention-based Encoder-Decoder，在单一高效模型中完成声学编码与自回归解码；官方接口可返回词级时间戳与置信度，2ByteASR 只把它用于时间轴和交叉证据。': ('FireRedASR2-AED uses an attention-based encoder-decoder and can return word-level timestamps and confidence in one model.', 'FireRedASR2-AEDはAttention-based Encoder-Decoderを採用し、音響エンコードと自己回帰デコードを単一モデルで実行します。公式APIは単語時刻と信頼度を返せます。2ByteASRでは時刻調整と照合用の根拠として使用します。'), '擅长补足字词首尾边界，适合作为 MOSS 初稿之后的时间轴阶段。': ('Strong word-boundary evidence for the timeline stage.', '文字・単語の開始と終了を補うのが得意で、MOSSの下書き後の時刻調整に適しています。'), '本机运行需要 CUDA；时间戳质量仍会受原始音频、多人重叠说话影响。': ('Local use requires CUDA; overlap and source audio quality still affect timestamps.', 'ローカル実行にはCUDAが必要です。時刻の精度は音声品質や複数話者の重なりにも左右されます。'), '输入音频；输出识别文字与可用于字幕切分的时间边界。': ('Input: audio. Output: recognized text and subtitle-ready boundaries.', '音声を入力し、認識テキストと字幕分割に使える時刻境界を出力します。'), 'FireRedASR 官方项目。': ('FireRedASR official project.', 'FireRedASR公式プロジェクト。'), '官方 README 未单列 AED 参数量': ('Not separately published for the AED checkpoint', '公式READMEにAED単体のパラメーター数の記載なし'), '中文（普通话）': ('Chinese (Mandarin)', '中国語（普通話）'), '20+ 中文方言/口音；官方列举粤语、四川、上海、吴语、闽南等': ('20+ Chinese dialects and accents; official examples include Cantonese, Sichuan, Shanghai, Wu and Minnan', '20以上の中国語方言・アクセント。公式には広東語、四川語、上海語、呉語、閩南語などを記載'), '语音、歌唱、歌词': ('Speech, singing and lyrics', '発話、歌唱、歌詞'), '支持中英混说': ('Chinese-English code switching', '中国語と英語の混在に対応'), '支持语音与歌唱转写': ('Speech and singing transcription supported', '発話と歌唱の文字起こしに対応'), '方言': ('Dialects', '方言'), '歌词识别': ('Lyrics', '歌詞認識'), 'Mandarin 4 集平均': ('Mandarin, 4-set average', '普通話4データセット平均'), 'FireRedASR2S README（仓库 2026-08-15 状态）': ('Official source reviewed 2026-09-18', 'FireRedASR2S README（2026-08-15時点のリポジトリ）'), '中文方言/口音 19 集平均': ('Chinese dialects/accents, 19-set average', '中国語方言・アクセント19データセット平均'), 'FireRedASR2-AED；19 个公开方言/口音测试集': ('Official checkpoint evaluation; see the source for the exact setup.', 'FireRedASR2-AED：19の公開方言・アクセントテストセット'), '相对推理速度': ('Relative inference speed', '相対推論速度'), 'FireRedASR2-AED TensorRT-LLM 对比 PyTorch baseline': ('Official checkpoint evaluation; see the source for the exact setup.', 'FireRedASR2-AEDのTensorRT-LLMとPyTorchベースラインの比較'), '单张 NVIDIA H20': ('One NVIDIA H20', 'NVIDIA H20 1枚'), '越高越好': ('Higher is better', '高いほど良い'), '官方准确度评测覆盖 24 个公开测试集；中文用 CER、英文用 WER，均越低越好。TensorRT 12.7x 加速数据使用单张 H20，不与准确度指标混算。': ('Official accuracy evaluation covers 24 public sets. The 12.7x TensorRT figure uses AISHELL-1 on one H20 and is not mixed with accuracy metrics.', '公式精度評価は24の公開テストセットを対象とし、中国語はCER、英語はWERで、いずれも低いほど良い指標です。TensorRTの12.7倍高速化はH20 1枚で測定したもので、精度指標とは分けて扱います。'), '官方仅验证 Ubuntu 22.04；AED 单段建议不超过 60 秒，超过 200 秒会触发位置编码错误。2ByteASR 已在 UI 外的现有分块流程中满足该限制。': ('Official support targets Ubuntu 22.04. AED segments should stay below the documented duration limit; 2ByteASR keeps its existing chunking path.', '公式検証環境はUbuntu 22.04のみ。AEDは1区間60秒以下を推奨し、200秒超では位置エンコーディングエラーになります。2ByteASRは既存の分割処理でこの制約を満たしています。'), '时间边界能力更适合第二阶段字幕时间轴。': ('Strong word-boundary evidence for the timeline stage.', '時刻境界の推定に優れ、第2段階の字幕タイミング調整に適しています。'), '多语言文字复核与术语证据补充。': ('Multilingual text review and terminology evidence.', '多言語テキストの確認と用語の照合。'), '在 2ByteASR 第三阶段对同一音频提供独立多语言转写结果，用于发现 MOSS 主稿中的文字、专名和混合语种差异；它不覆盖 MOSS 的说话人身份，也不直接重写时间轴。': ('Produces an independent transcript for the same audio to reveal wording, named-entity and mixed-language differences without replacing speaker identity or the timeline.', '2ByteASRの第3段階で同じ音声を独立して多言語認識し、MOSS原稿の文字、固有名詞、混在言語の差を確認します。MOSSの話者情報を上書きせず、タイムラインも直接書き換えません。'), 'Qwen3-ASR 是统一流式/离线的自回归语音识别模型，基于 Qwen3-Omni 的音频理解能力，同时完成语种识别和转写；需要时间戳时再配合独立的 Qwen3-ForcedAligner 非自回归对齐模型。': ('Qwen3-ASR is a unified streaming/offline autoregressive recognizer derived from Qwen3-Omni; timestamps are handled by the separate forced aligner.', 'Qwen3-ASRはストリーミングとオフラインを統合した自己回帰音声認識モデルです。Qwen3-Omniの音声理解を基盤に、言語識別と文字起こしを行います。時刻が必要な場合は独立した非自己回帰モデルQwen3-ForcedAlignerを併用します。'), '对专名、多语言片段和文字差异提供第二路本地参考。': ('Strong independent evidence for names and multilingual passages.', '固有名詞、多言語区間、テキストの差に対し、2つ目のローカル認識結果を提供します。'), '下载体积与显存占用较高；它在本项目中是复核角色，不替代完整任务流程。': ('Requires a substantial download and GPU memory; it remains a review stage in this workflow.', 'ダウンロード容量とVRAM使用量が大きめです。このアプリでは確認役であり、処理全体を置き換えません。'), '输入已分段的音频/文本上下文；输出文字候选和复核证据。': ('Input: segmented audio and optional text context. Output: text candidates and review evidence.', '分割音声とテキストの文脈を入力し、候補テキストと確認用の根拠を出力します。'), 'Qwen3-ASR 官方发布版本与 2ByteASR 本地适配。': ('Qwen3-ASR official release + 2ByteASR local adapter.', 'Qwen3-ASR公式版と2ByteASRのローカル実装。'), '中文': ('Chinese', '中国語'), '粤语': ('Cantonese', '広東語'), '阿拉伯语': ('Arabic', 'アラビア語'), '德语': ('German', 'ドイツ語'), '法语': ('French', 'フランス語'), '西班牙语': ('Spanish', 'スペイン語'), '葡萄牙语': ('Portuguese', 'ポルトガル語'), '印尼语': ('Indonesian', 'インドネシア語'), '意大利语': ('Italian', 'イタリア語'), '韩语': ('Korean', '韓国語'), '俄语': ('Russian', 'ロシア語'), '泰语': ('Thai', 'タイ語'), '越南语': ('Vietnamese', 'ベトナム語'), '日语': ('Japanese', '日本語'), '土耳其语': ('Turkish', 'トルコ語'), '印地语': ('Hindi', 'ヒンディー語'), '马来语': ('Malay', 'マレー語'), '荷兰语': ('Dutch', 'オランダ語'), '瑞典语': ('Swedish', 'スウェーデン語'), '丹麦语': ('Danish', 'デンマーク語'), '芬兰语': ('Finnish', 'フィンランド語'), '波兰语': ('Polish', 'ポーランド語'), '捷克语': ('Czech', 'チェコ語'), '菲律宾语': ('Filipino', 'フィリピノ語'), '波斯语': ('Persian', 'ペルシア語'), '希腊语': ('Greek', 'ギリシャ語'), '匈牙利语': ('Hungarian', 'ハンガリー語'), '马其顿语': ('Macedonian', 'マケドニア語'), '罗马尼亚语': ('Romanian', 'ルーマニア語'), '22 种中文方言/口音，官方 README 已逐项列出': ('22 Chinese dialects and accents, fully listed in the official README', '中国語の22方言・アクセント。公式READMEに全項目を記載'), '语音、歌唱、带 BGM 歌曲': ('Speech, singing voice and songs with BGM', '発話、歌唱、BGM付きの歌'), '官方未单独声明 code-switching 范围': ('Code-switching scope is not stated separately', '言語混在への対応範囲は公式に個別の記載なし'), '支持歌唱与带 BGM 歌曲': ('Singing voice and songs with BGM supported', '歌唱とBGM付きの歌に対応'), '语种识别': ('Language ID', '言語識別'), '流式/离线': ('Streaming/offline', 'ストリーミング・オフライン'), '歌唱识别': ('Singing', '歌唱認識'), 'Qwen3-ASR-1.7B；官方同表中文评测（同表 Whisper-large-v3 5.06 / GPT-4o 4.24 / Doubao 2.85）': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR-1.7B：公式同一表の中国語評価（Whisper-large-v3 5.06 / GPT-4o 4.24 / Doubao 2.85）'), '官方未声明具体 GPU': ('Not stated in directly comparable form', '具体的なGPUは公式未記載'), 'Qwen3-ASR README（2026-09-18 核对）': ('Official source reviewed 2026-09-18', 'Qwen3-ASR README（2026-09-18確認）'), 'Qwen3-ASR-1.7B；官方同表（同表 Whisper-large-v3 9.86 / Gemini-2.5-Pro 14.43）': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR-1.7B：公式同一表（Whisper-large-v3 9.86 / Gemini-2.5-Pro 14.43）'), 'Qwen3-ASR-1.7B；官方同表（同表 Whisper-large-v3 19.11 / Gemini-2.5-Pro 13.47）': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR-1.7B：公式同一表（Whisper-large-v3 19.11 / Gemini-2.5-Pro 13.47）'), 'Qwen3-ASR-1.7B；官方同表（同表 Whisper-large-v3 7.56 / Doubao 2.93）': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR-1.7B：公式同一表（Whisper-large-v3 7.56 / Doubao 2.93）'), 'Qwen3-ASR-1.7B；离线模式；统一官方评测设置': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR-1.7B：オフラインモード、統一された公式評価条件'), 'Qwen3-ASR-1.7B；官方同表': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR-1.7B：公式同一表'), 'KeSpeech（方言）': ('KeSpeech (dialects)', 'KeSpeech（方言）'), 'Qwen3-ASR-1.7B；官方同表（同表 Whisper-large-v3 28.79）': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR-1.7B：公式同一表（Whisper-large-v3 28.79）'), 'Fleurs-yue（粤语）': ('Fleurs-yue (Cantonese)', 'Fleurs-yue（広東語）'), 'Qwen3-ASR-1.7B；vLLM；bfloat16；max_new_tokens=1024；greedy；不指定语言（英语 WER，不代表中文 CER）': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR-1.7B：vLLM、bfloat16、max_new_tokens=1024、greedy、言語指定なし（英語WERであり、中国語CERではありません）'), 'Qwen3-ASR-1.7B；vLLM；bfloat16；max_new_tokens=1024；greedy；不指定语言': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR-1.7B：vLLM、bfloat16、max_new_tokens=1024、greedy、言語指定なし'), 'MLS（8 语种）': ('MLS (8 languages)', 'MLS（8言語）'), 'Qwen3-ASR-1.7B；官方多语言公开集汇总': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR-1.7B：公式の公開多言語データセット集計'), 'Qwen3-ASR README（仓库 2026-08-15 状态）': ('Official source reviewed 2026-09-18', 'Qwen3-ASR README（2026-08-15時点のリポジトリ）'), 'CommonVoice（13 语种）': ('CommonVoice (13 languages)', 'CommonVoice（13言語）'), 'Qwen3-ASR-1.7B；歌唱转写评测': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR-1.7B：歌唱文字起こし評価'), '官方统一使用 vLLM、bfloat16、max_new_tokens=1024、greedy decoding，且测试不指定语言参数。中文集行为 2026-09-18 补核；LibriSpeech/MLS/CommonVoice 为英语或多语 WER，不与中文 CER 混排。': ('Official evaluation uses vLLM, bfloat16, greedy decoding and no explicit language parameter.', '公式評価はvLLM、bfloat16、max_new_tokens=1024、greedy decodingで統一され、言語は指定しません。中国語データは2026-09-18に追加確認。LibriSpeech/MLS/CommonVoiceの英語・多言語WERは中国語CERと混在させません。'), '官方建议独立 Python 3.12 环境，并推荐 FlashAttention 2；Transformers 与 vLLM 均支持 CUDA，本地 1.7B 仍需按批大小控制显存。': ('The official project recommends an isolated Python 3.12 environment and FlashAttention 2 where available.', '公式は独立したPython 3.12環境とFlashAttention 2を推奨。TransformersとvLLMはCUDAに対応します。ローカル1.7BモデルではバッチサイズでVRAM使用量を調整する必要があります。'), '文字准确度与专名复核能力适合作为第三阶段复核。': ('Strong independent evidence for names and multilingual passages.', 'テキスト精度と固有名詞の確認に優れ、第3段階の確認に適しています。'), '轻量多语言语音识别与文字复核。': ('Lightweight multilingual recognition and text review.', '軽量な多言語音声認識とテキスト確認。'), '作为低资源本地后端，为中文、粤语和常见多语种提供第二路文字证据；独立 SenseVoiceSmall checkpoint 不承担说话人分离。': ('Provides a low-resource second transcript for Chinese, Cantonese, English, Japanese and Korean; the checkpoint itself does not perform speaker separation.', '低リソースのローカルバックエンドとして、中国語、広東語、一般的な多言語に独立した認識結果を提供します。SenseVoiceSmall単体は話者分離を行いません。'), 'SenseVoiceSmall 采用非自回归端到端框架，一次前向同时输出转写、语种、情感和音频事件标签；长音频通过 FunASR 的独立 VAD 分段处理。': ('A non-autoregressive model emits transcription, language, emotion and audio-event labels in one pass; FunASR VAD handles long audio separately.', 'SenseVoiceSmallは非自己回帰のエンドツーエンド方式で、1回の推論からテキスト、言語、感情、音響イベントを出力します。長時間音声はFunASRの独立VADで分割します。'), 'CPU 也可使用，对中文、粤语和常见多语种较友好。': ('CPU-capable and especially practical for Chinese and Cantonese.', 'CPUでも使用でき、中国語、広東語、一般的な多言語に対応します。'), '当前不提供 MOSS 的多人说话人骨架；更适合做独立文字证据。': ('Does not provide the MOSS multi-speaker backbone.', 'MOSSの複数話者の骨格は提供しません。独立したテキスト照合に適しています。'), '输入音频；输出多语言文字结果及可选事件/情感信息。': ('Input: audio. Output: multilingual text with optional emotion and event labels.', '音声を入力し、多言語テキストと任意のイベント・感情情報を出力します。'), 'FunAudioLLM SenseVoice 官方项目。': ('FunAudioLLM SenseVoice official project.', 'FunAudioLLM SenseVoice公式プロジェクト。'), '约 234M（与 Whisper-Small 同级）': ('Approx. 234M', '約234M（Whisper-Smallと同規模）'), '非自回归端到端音频理解模型': ('Non-autoregressive end-to-end audio understanding', '非自己回帰のエンドツーエンド音声理解モデル'), '粤语；该 checkpoint 未单列其它中文方言': ('Cantonese; no other Chinese dialects are listed for this checkpoint', '広東語。このチェックポイントでは他の中国語方言は個別未記載'), '语音 + 情感/事件标签': ('Speech with optional emotion and event labels', '発話と感情・イベントラベル'), '代码 MIT；权重为 FunASR 模型协议': ('MIT code; FunASR model license for weights', 'コードはMIT、重みはFunASRモデルライセンス'), '情感': ('Emotion', '感情'), '音频事件': ('Audio events', '音響イベント'), 'SenseVoice 技术报告 Table 6（同表 Whisper-Small 10.04 / Whisper-Large-v3 5.14）': ('Official checkpoint evaluation; see the source for the exact setup.', 'SenseVoice技術報告Table 6（同一表：Whisper-Small 10.04 / Whisper-Large-v3 5.14）'), 'arXiv 2407.04051v3（2026-09-18 核对）': ('Official source reviewed 2026-09-18', 'arXiv 2407.04051v3（2026-09-18確認）'), 'SenseVoice 技术报告 Table 6': ('Official checkpoint evaluation; see the source for the exact setup.', 'SenseVoice技術報告Table 6'), 'SenseVoice 技术报告 Table 6（英语 WER，不代表中文 CER）': ('Official checkpoint evaluation; see the source for the exact setup.', 'SenseVoice技術報告Table 6（英語WERであり、中国語CERではありません）'), '推理延迟': ('Inference latency', '推論レイテンシー'), '10 秒音频端到端延迟': ('10-second audio end-to-end latency', '10秒音声のエンドツーエンドレイテンシー'), 'SenseVoice 技术报告 Table 7；延迟指标，不与 RTF/吞吐互换': ('Official checkpoint evaluation; see the source for the exact setup.', 'SenseVoice技術報告Table 7：遅延指標であり、RTFやスループットとは換算できません'), '报告实验环境': ('Not stated in directly comparable form', '技術報告の実験環境'), '官方 inference benchmark': ('Official inference benchmark', '公式推論ベンチマーク'), 'SenseVoiceSmall 对比 Whisper-Small；同一官方图示条件': ('Official checkpoint evaluation; see the source for the exact setup.', 'SenseVoiceSmallとWhisper-Small：公式図の同一条件で比較'), '具体硬件见官方 benchmark 图': ('Not stated in directly comparable form', 'ハードウェアの詳細は公式ベンチマーク図を参照'), 'SenseVoice README（仓库 2026-09-18 状态）': ('Official source reviewed 2026-09-18', 'SenseVoice README（2026-09-18時点のリポジトリ）'), 'SenseVoiceSmall 对比 Whisper-Large；同一官方图示条件': ('Official checkpoint evaluation; see the source for the exact setup.', 'SenseVoiceSmallとWhisper-Large：公式図の同一条件で比較'), '准确率数值来自 SenseVoice 技术报告 Table 6（2026-09-18 核对）；README 的详细准确率表仍以图片发布、无法逐项核对，速度倍数仅引用 README 明文。同表 Whisper-Large-v3 数值（AISHELL-1 5.14 等）属对照系统且非本工程 turbo checkpoint，只在此备注、不并入其卡片。': ('The official README publishes the detailed accuracy table as an image; this page only uses directly verifiable text values.', '精度値はSenseVoice技術報告Table 6から引用（2026-09-18確認）。READMEの詳細精度表は画像で、項目別の照合ができないため、速度倍率は本文の記載のみを引用。同一表のWhisper-Large-v3（AISHELL-1 5.14など）は比較用モデルで、このアプリのturboチェックポイントとは異なるため、そのカードには反映しません。'), '支持 CUDA、ONNX、libtorch 与 llama.cpp/GGUF CPU 路径；说话人分离需另配 FSMN-VAD + CAM++，不是 checkpoint 原生能力。': ('Supports CUDA, ONNX, libtorch and llama.cpp/GGUF CPU paths. Speaker labels require separate VAD and CAM++ models.', 'CUDA、ONNX、libtorch、llama.cpp/GGUFによるCPU実行に対応。話者分離には別途FSMN-VADとCAM++が必要で、モデル単体の機能ではありません。'), '轻量多语言，适合作为独立文字证据或低资源场景的备选。': ('CPU-capable and especially practical for Chinese and Cantonese.', '軽量な多言語対応。独立したテキスト照合や低リソース環境の候補に適しています。'), '中文长音频识别与轻量时间轴后端。': ('Chinese long-audio recognition and a lightweight timeline backend.', '中国語の長時間音声認識と軽量な時刻調整バックエンド。'), '在 2ByteASR 中作为可选中文时间轴后端，以非自回归识别和时间戳补充 MOSS 初稿；它不替代 MOSS 的多人说话人骨架。': ('Provides optional Chinese text and timestamps after the MOSS draft; it does not replace the multi-speaker backbone.', '2ByteASRでは任意の中国語タイミング調整用として、非自己回帰認識と時刻でMOSSの下書きを補います。MOSSの複数話者の骨格は置き換えません。'), 'Paraformer 是非自回归端到端 ASR：编码器提取声学表示，预测器估计目标长度并生成声学向量，解码器并行输出文字；FunASR 再组合 VAD、标点和热词形成长音频 pipeline。': ('A non-autoregressive encoder, predictor and decoder generate text in parallel; FunASR composes VAD, punctuation and hot words for long audio.', 'Paraformerは非自己回帰ASRです。エンコーダーが音響表現を抽出し、予測器が出力長と音響ベクトルを生成、デコーダーがテキストを並列出力します。FunASRはVAD、句読点、ホットワードを組み合わせて長時間音声を処理します。'), '非自回归路线、支持热词，可与 VAD/标点组件配合，速度取向明显。': ('Fast non-autoregressive inference with hot-word support.', '非自己回帰方式でホットワードに対応し、VAD・句読点処理と併用できます。速度を重視した構成です。'), '当前 2ByteASR 将它用于时间轴角色；主力多人转写仍以 MOSS 为准。': ('The installed checkpoint is Chinese-specific, not the multilingual Paraformer family.', '現在の2ByteASRでは時刻調整に使用します。複数話者の主文字起こしはMOSSが担当します。'), '输入音频与可选热词；输出中文文字和后端提供的时间信息。': ('Input: audio and optional hot words. Output: Chinese text and timing evidence.', '音声と任意のホットワードを入力し、中国語テキストとバックエンドの時刻情報を出力します。'), 'ModelScope FunASR 官方项目。': ('ModelScope FunASR official project.', 'ModelScope FunASR公式プロジェクト。'), '约 220M': ('Approx. 220M', '約220M'), 'Paraformer 非自回归端到端 ASR': ('Paraformer non-autoregressive end-to-end ASR', 'Paraformer非自己回帰エンドツーエンドASR'), '官方模型卡未单列方言覆盖': ('The official model card does not list dialect coverage', '対応方言は公式モデルカードに個別の記載なし'), '16 kHz 中文语音；长音频由 VAD pipeline 分段': ('16 kHz Chinese speech; VAD handles long audio', '16 kHz中国語音声。長時間音声はVADで分割'), '模型页所列 Apache-2.0': ('Apache-2.0 as listed on the model card', 'モデルページ記載のApache-2.0'), '热词': ('Chinese', 'ホットワード'), 'Paraformer Large 官方卡 w/o LM 解码（w/ LM 1.68）；同表对照 Espnet 4.90 / WeNet 4.61': ('Official checkpoint evaluation; see the source for the exact setup.', 'Paraformer Large公式カードのw/o LMデコード（w/ LMは1.68）。同一表の比較値：Espnet 4.90 / WeNet 4.61'), '官方 ModelScope 模型卡（2026-09-18 核对，卡片 v2.0.4）': ('Official source reviewed 2026-09-18', '公式ModelScopeモデルカード（2026-09-18確認、カードv2.0.4）'), 'Paraformer Large 官方卡（同表 WeNet test_ios 5.39）': ('Official checkpoint evaluation; see the source for the exact setup.', 'Paraformer Large公式カード（同一表：WeNet test_ios 5.39）'), '官方 ModelScope 模型卡（2026-09-18 核对）': ('Official source reviewed 2026-09-18', '公式ModelScopeモデルカード（2026-09-18確認）'), 'Paraformer Large 官方卡（test_android 3.13 / test_mic 3.06）': ('Official checkpoint evaluation; see the source for the exact setup.', 'Paraformer Large公式カード（test_android 3.13 / test_mic 3.06）'), 'Paraformer Large 官方卡 w/o LM': ('Official checkpoint evaluation; see the source for the exact setup.', 'Paraformer Large公式カード、w/o LM'), 'Paraformer Large 官方卡 w/o LM（同表 Espnet 15.90 / WeNet 17.34 / K2 13.41）': ('Official checkpoint evaluation; see the source for the exact setup.', 'Paraformer Large公式カード、w/o LM（同一表：Espnet 15.90 / WeNet 17.34 / K2 13.41）'), '官方卡 indexing 结果': ('Official model card indexing results', '公式カードのindexing結果'), 'GPU 推理 V100、batch_size=1；官方参考速度，与本机或其它硬件不可直接互比': ('Official checkpoint evaluation; see the source for the exact setup.', 'V100によるGPU推論、batch_size=1。公式参考速度であり、手元のPCや他のハードウェアとは直接比較できません'), '数值来自 Paraformer Large 官方模型卡当前表格（2026-09-18 核对，卡片 v2.0.4）；不同 pipeline 组件、热词和音频分段策略会改变实际结果。RTF 为官方 V100 参考值，不参与跨模型速度排名。': ('Values come from the official Paraformer Large model card; VAD, punctuation and hot-word settings can change real results.', 'Paraformer Large公式モデルカードの表から引用（2026-09-18確認、v2.0.4）。構成、ホットワード、音声分割方法で実測結果は変わります。RTFは公式V100参考値で、モデル間の速度順位には使用しません。'), '官方支持 CPU/CUDA 与 ONNX 路径；2ByteASR 实际建议按现有独立 FunASR 环境运行，长音频继续使用既有 VAD 分块。': ('Official CPU, CUDA and ONNX paths are available; 2ByteASR keeps its existing isolated FunASR environment.', '公式はCPU/CUDAとONNXに対応。2ByteASRでは既存の独立FunASR環境とVAD分割の使用を推奨します。'), '非自回归 + 热词，速度取向，适合时间轴/轻量中文场景。': ('Fast non-autoregressive inference with hot-word support.', '非自己回帰方式とホットワードに対応。速度重視の時刻調整や軽量な中国語処理に適しています。'), '通用多语言语音转写与复核。': ('General multilingual transcription and review.', '汎用の多言語文字起こしと確認。'), '在 2ByteASR 中作为可选多语种文字复核或时间轴证据，适合中文之外及混合语种片段；不承担 MOSS 的说话人区分。': ('Adds multilingual text or timing evidence for non-Chinese and mixed-language clips without speaker separation.', '2ByteASRでは多言語テキスト確認や時刻の補助情報として選択できます。中国語以外や混在言語に適し、MOSSの話者分離は担当しません。'), 'Whisper 是编码器-解码器 Transformer：把音频转成 log-Mel 频谱，由多任务序列 token 同时表达语种、转写/翻译与时间戳。large-v3-turbo 缩短了解码器以换取更快推理。': ('An encoder-decoder Transformer predicts language, transcription or translation and timestamp tokens from log-Mel audio features.', 'Whisperはencoder-decoder Transformerです。音声をlog-Melスペクトルに変換し、系列トークンで言語、文字起こし・翻訳、時刻を表現します。large-v3-turboはデコーダーを短縮して推論を高速化しています。'), '语言覆盖广，适合混合语种或非中文内容提供第二路证据。': ('Broad language coverage and mature runtime support.', '言語対応が広く、中国語以外や混在言語の照合に適しています。'), '不包含 MOSS 的说话人区分；不同硬件上的速度差异较大。': ('No MOSS-style speaker separation; speed varies substantially by hardware and runtime.', 'MOSSの話者分離は含みません。処理速度はハードウェアに大きく左右されます。'), '输入音频；输出转写文字和片段级时间信息。': ('Input: audio. Output: text and segment-level timing.', '音声を入力し、文字起こしテキストと区間単位の時刻を出力します。'), 'OpenAI Whisper 官方项目。': ('OpenAI Whisper official project.', 'OpenAI Whisper公式プロジェクト。'), '官方 tokenizer 列出的多语言集合': ('Official tokenizer language set', '公式トークナイザーに記載された対応言語'), '官方未提供独立方言清单': ('No separate official dialect list', '方言の独立した一覧は公式未公開'), '通用语音；30 秒窗口与长音频滑窗': ('General speech in 30-second windows', '一般音声。30秒窓と長時間音声のスライディングウィンドウ処理'), '官方未将歌唱列为独立能力': ('Singing is not listed as a separate capability', '歌唱は公式に独立した能力として記載なし'), 'HF OpenASR 榜单 8 集均值（英语）': ('HF OpenASR leaderboard mean, 8 sets (English)', 'HF OpenASRランキングの8データセット平均（英語）'), 'whisper-large-v3-turbo；官方 HF 模型卡所载 OpenASR 榜单结果（whisper-normalizer 口径）': ('Official checkpoint evaluation; see the source for the exact setup.', 'whisper-large-v3-turbo：公式HFモデルカードに記載されたOpenASR結果（whisper-normalizer基準）'), 'OpenASR 榜单统一环境': ('Not stated in directly comparable form', 'OpenASRランキングの統一環境'), 'openai/whisper-large-v3-turbo HF 模型卡（2026-09-18 核对）': ('Official source reviewed 2026-09-18', 'openai/whisper-large-v3-turbo HFモデルカード（2026-09-18確認）'), 'whisper-large-v3-turbo；英语 WER': ('Official checkpoint evaluation; see the source for the exact setup.', 'whisper-large-v3-turbo：英語WER'), 'HF OpenASR 榜单（英语）': ('HF OpenASR leaderboard (English)', 'HF OpenASRランキング（英語）'), 'whisper-large-v3-turbo；RTFx=1/RTF，越高越快；榜单统一环境参考，不代表本机速度': ('Official checkpoint evaluation; see the source for the exact setup.', 'whisper-large-v3-turbo：RTFx=1/RTFで高いほど高速。ランキング環境の参考値であり、手元のPCの速度ではありません'), '官方 large-v3-turbo 模型卡未发布逐中文数据集数值表；此处英语成绩来自官方卡所载 OpenASR 榜单（独立评测口径），中文能力没有同协议横评数据，不在中文场景评分。': ('The turbo model card does not provide one directly comparable per-dataset table for the models on this page.', '公式large-v3-turboモデルカードには中国語データセット別の値がありません。英語成績は公式カード掲載のOpenASRによる独立評価です。中国語は同一条件の比較データがなく、スコアを付けません。'), '官方模型卡列出约 6 GB 相对显存需求；2ByteASR 可使用现有 CUDA 后端，本机速度仍取决于实现与音频长度。': ('The official card lists about 6 GB relative VRAM; actual local speed depends on runtime and audio length.', '公式モデルカードのVRAM目安は約6 GB。2ByteASRの既存CUDAバックエンドを使用できますが、速度は実装と音声の長さに依存します。'), '多语言覆盖广，适合非中文或混合语种的第二路证据。': ('Broad language coverage and mature runtime support.', '言語対応が広く、中国語以外や混在言語の独立した照合に適しています。'), '依据已有文字生成字/词级时间边界。': ('Character and word timing from existing text.', '既存テキストに基づいて文字・単語の時刻境界を生成。'), '在 2ByteASR 中可替换 FireRed 的时间轴角色：接收已经确认的文字和音频，只计算字词对齐，不重新决定字幕内容。': ('Can replace the timeline backend by aligning confirmed text to audio without deciding the transcript again.', '2ByteASRでFireRedの時刻調整役を置き換えられます。確認済みテキストと音声を受け取り、内容を決め直さずに文字・単語を整列します。'), 'Qwen3-ForcedAligner 是非自回归强制对齐模型，同时读取音频和给定文本，直接预测每个字符或单词的时间位置；它不是从零开始的语音转写模型。': ('A non-autoregressive forced aligner reads audio and supplied text and predicts character or word positions.', 'Qwen3-ForcedAlignerは非自己回帰の強制アラインメントモデルです。音声と指定テキストから各文字・単語の時刻を直接予測します。音声から新たに文字起こしを行うモデルではありません。'), '当主稿可靠时能把文字稳定映射到多语种字词时间戳，避免对齐阶段再次改写原文。': ('Preserves trusted text while generating multilingual fine timing.', '原稿が正確であれば、多言語の文字・単語を時刻に対応付け、アラインメント中の原文変更を防げます。'), '必须先有可靠文本；错字、漏字、多人重叠和强噪声会直接影响对齐，且本地运行需要 CUDA。': ('Requires reliable input text; omissions, overlap and noise directly affect alignment.', '信頼できるテキストが必要です。誤字、脱字、話者の重なり、強い雑音は整列精度に直接影響します。ローカル実行にはCUDAが必要です。'), '输入音频 + 已有文字；输出字符/单词的起止时间。': ('Input: audio plus existing text. Output: character or word boundaries.', '音声と既存テキストを入力し、文字・単語の開始・終了時刻を出力します。'), 'Qwen3-ForcedAligner 官方模型卡。': ('Qwen3-ForcedAligner official model card.', 'Qwen3-ForcedAligner公式モデルカード。'), '非自回归 forced alignment': ('Non-autoregressive forced alignment', '非自己回帰の強制アラインメント'), '官方未单列方言；对齐输入必须已有文字': ('No dialect list; alignment requires existing text', '方言は公式に個別の記載なし。整列には既存テキストが必要'), '语音 + 已知转写文本': ('Speech plus known transcript text', '発話と既知の文字起こしテキスト'), '仅声明 Speech': ('Speech only', '発話のみを対象として記載'), '字级对齐': ('Character alignment', '文字単位の整列'), '词级对齐': ('Word alignment', '単語単位の整列'), '原文保留': ('Text preservation', '原文を保持'), 'MFA Raw 中文': ('MFA Raw Chinese', 'MFA Raw中国語'), 'Qwen3-ForcedAligner-0.6B；官方 alignment 评测': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ForcedAligner-0.6B：公式アラインメント評価'), 'MFA Raw 英文': ('MFA Raw English', 'MFA Raw英語'), 'AAS 表示平均对齐偏差，单位毫秒，越低越好；该指标只衡量给定文本的对齐，不代表从零转写准确率。': ('AAS is average alignment deviation in milliseconds and does not represent transcription accuracy.', 'AASは平均アラインメント偏差をミリ秒で表し、低いほど良い指標です。指定テキストの整列のみを評価し、音声からの文字起こし精度は表しません。'), '官方 qwen-asr 路径使用 CUDA；2ByteASR 实际建议把它放在可靠主稿之后，避免把文本错误传递给对齐阶段。': ('The official qwen-asr path uses CUDA and should run after a reliable transcript is available.', '公式qwen-asr実装はCUDAを使用します。2ByteASRでは正確な原稿の後に使用し、テキスト誤りが時刻調整へ波及しないようにすることを推奨します。'), '只对齐已有文字，适合在不改写主稿的前提下生成多语种字词时间戳。': ('Preserves trusted text while generating multilingual fine timing.', '既存テキストのみを整列します。原稿を変更せずに多言語の文字・単語時刻を生成する用途に適しています。'), '中文方言与多语种的本地文字复核。': ('Local review for Chinese dialects, English and Japanese.', '中国語方言・多言語のローカルテキスト確認。'), '在 2ByteASR 中作为可选本地复核后端，为中文方言和多语种片段提供第二路文字证据；不承担多人说话人骨架。': ('Provides independent text evidence for Chinese dialects, regional accents, English and Japanese; it does not create the multi-speaker backbone.', '2ByteASRでは任意のローカル確認バックエンドとして、中国語方言や多言語区間の独立した認識結果を提供します。複数話者の骨格は担当しません。'), 'Fun-ASR-Nano 采用音频编码器连接语言模型的端到端路线，直接生成转写文本，并通过可配置上下文增强专名与热词；2ByteASR 仅消费其独立文字证据。': ('An audio encoder connects to a language model for end-to-end transcription with optional context and hot-word enhancement.', 'Fun-ASR-Nanoは音声エンコーダーと言語モデルを接続し、文字起こしを直接生成します。設定可能な文脈で固有名詞・ホットワードを補強し、2ByteASRは独立した照合用テキストとして利用します。'), '兼顾中文方言、多语种和上下文增强，适合专名较多的游戏内容复核。': ('Strong checkpoint-specific Chinese dialect coverage plus lyrics and rap recognition.', '中国語方言、多言語、文脈による補強に対応。固有名詞の多いゲーム素材の確認に適しています。'), '0.8B 本地模型仍需要独立运行环境和显存；作为复核后端不提供 MOSS 的说话人区分。': ('The installed Nano checkpoint is not the separate 31-language MLT-Nano checkpoint and has no native speaker separation.', '0.8Bのローカルモデルにも独立した実行環境とVRAMが必要です。確認用のためMOSSの話者分離は提供しません。'), '输入音频与可选上下文；输出多语言/方言转写文字。': ('Input: audio and optional context. Output: Chinese, English, Japanese and dialect text.', '音声と任意の文脈を入力し、多言語・方言の文字起こしを出力します。'), 'FunAudioLLM Fun-ASR 官方项目。': ('FunAudioLLM Fun-ASR official project.', 'FunAudioLLM Fun-ASR公式プロジェクト。'), '音频编码器 + LLM 的端到端 ASR': ('Audio encoder + LLM end-to-end ASR', '音声エンコーダーとLLMによるエンドツーエンドASR'), '吴、粤、闽、客家、赣、湘、晋 7 大方言；26 种地域口音': ('Wu, Cantonese, Min, Hakka, Gan, Xiang and Jin; 26 regional accents', '呉、粤、閩、客家、贛、湘、晋の7大方言と26地域のアクセント'), '语音、长音频分块': ('Speech and long-audio chunks', '発話、長時間音声の分割処理'), '以官方模型卡协议为准': ('See the official checkpoint model card', '公式モデルカードのライセンスに従う'), '支持歌词与说唱识别': ('Lyrics and rap recognition supported', '歌詞とラップの認識に対応'), '中文方言': ('Chinese', '中国語方言'), '上下文增强': ('Japanese', '文脈による補強'), 'Fun-ASR-Nano-2512 官方模型卡自报（同表 Fun-ASR 7.7B 1.22，闭源）': ('Official checkpoint evaluation; see the source for the exact setup.', 'Fun-ASR-Nano-2512公式モデルカードの自己申告値（同一表：Fun-ASR 7.7B 1.22、非公開モデル）'), 'Fun-ASR HF 模型卡（2026-09-18 核对）': ('Official source reviewed 2026-09-18', 'Fun-ASR HFモデルカード（2026-09-18確認）'), 'Fun-ASR-Nano-2512 官方模型卡自报': ('Official checkpoint evaluation; see the source for the exact setup.', 'Fun-ASR-Nano-2512公式モデルカードの自己申告値'), 'Fun-ASR-Nano-2512 官方模型卡自报；Qwen3-ASR 官方表同集复测为 3.51，两来源并列保留、不合并': ('Official checkpoint evaluation; see the source for the exact setup.', 'Fun-ASR-Nano-2512の自己申告値。Qwen3-ASR公式表による同じデータの再評価は3.51で、両方を別々に保持します'), 'Fleurs-zh（Qwen3-ASR 官方表复测）': ('Fleurs-zh (Qwen3-ASR table retest)', 'Fleurs-zh（Qwen3-ASR公式表での再評価）'), 'Qwen3-ASR README 同表对 Fun-ASR-Nano 的复测值；与 Fun 自报 2.56 属不同评测管线': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR READMEによるFun-ASR-Nanoの再評価。Funの自己申告2.56とは異なる評価手順です'), 'WenetSpeech test_net（Qwen3-ASR 官方表复测）': ('WenetSpeech test_net (Qwen3-ASR table retest)', 'WenetSpeech test_net（Qwen3-ASR公式表での再評価）'), 'Qwen3-ASR README 同表复测；Fun 自报同集 6.01': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR READMEでの再評価。Funの同じデータの自己申告は6.01'), 'LibriSpeech test-clean（Qwen3-ASR 官方表复测）': ('LibriSpeech test-clean (Qwen3-ASR table retest)', 'LibriSpeech test-clean（Qwen3-ASR公式表での再評価）'), 'Qwen3-ASR README 同表复测；Fun 自报 1.76': ('Official checkpoint evaluation; see the source for the exact setup.', 'Qwen3-ASR READMEでの再評価。Funの自己申告は1.76'), 'Fun 自报值与 Qwen3-ASR 官方表复测值是两套评测管线，同名数据集数字有差异（Fleurs-zh 2.56 vs 3.51），按来源分行保留、绝不合并成一张榜。官方模型卡 TODO 明示：时间戳与说话人分离能力暂未随 2512 checkpoint 提供。': ('Official public-set values apply to Fun-ASR-Nano-2512; runtime and batching are not uniform with other models here.', 'Funの自己申告値とQwen3-ASRの再評価は異なる手順によるため、同じデータでも値が異なります（Fleurs-zh 2.56と3.51）。出典ごとに分けて保持し、ランキングを統合しません。公式モデルカードのTODOには、2512チェックポイントは時刻と話者分離に未対応と明記されています。'), '官方提供 FunASR/Transformers 路径；2ByteASR 实际建议使用现有独立模型环境，并按本机显存控制批量。': ('Requires an isolated FunASR environment; local GPU memory depends on runtime and batching.', '公式にはFunASR/Transformersの実装があります。2ByteASRでは既存の独立モデル環境を使い、VRAM容量に合わせてバッチを調整することを推奨します。'), '方言与多语种覆盖适合为游戏专名和口音片段补一份独立文字证据。': ('Strong checkpoint-specific Chinese dialect coverage plus lyrics and rap recognition.', '方言と多言語への対応により、ゲームの固有名詞やアクセントのある区間に独立した照合結果を提供します。'), '面向中文、方言与中英混说的高精度主力转写候选。': ('High-accuracy primary transcription candidate for Mandarin, dialects and English.', '中国語、方言、中国語と英語の混在向けの高精度な主文字起こし候補。'), '作为高级用户可选的主力转写模型；不替代默认 MOSS / FireRed AED / Qwen 组合，也不承担默认时间轴角色。': ('Advanced optional primary model; it does not replace the default MOSS / FireRed AED / Qwen workflow.', '上級者向けに選択できる主文字起こしモデルです。既定のMOSS / FireRed AED / Qwen構成や時刻調整役は置き換えません。'), '8B+ Encoder-Adapter-LLM：语音编码器经 Adapter 接入 Qwen2-7B-Instruct，利用语言模型完成端到端转写。': ('An 8B+ Encoder-Adapter-LLM that connects a speech encoder to Qwen2-7B-Instruct.', '8B以上のEncoder-Adapter-LLM構成。音声エンコーダーをAdapter経由でQwen2-7B-Instructに接続し、エンドツーエンドで文字起こしします。'), '官方中文普通话与 19 组方言评测均优于同表对比模型，并支持中英混说、语音与歌唱。': ('Strong official Mandarin and dialect CER results with code-switching and singing support.', '公式の普通話と19方言グループの評価で同一表の比較モデルを上回り、中国語と英語の混在、発話、歌唱に対応します。'), '单段音频最多 40 秒，权重和显存占用明显高于 AED；长视频仍必须由 2ByteASR 分块。': ('Audio input is limited to 40 seconds, so long media still requires chunking.', '1区間は最大40秒です。重みとVRAM使用量はAEDより大幅に多く、長い動画は2ByteASRによる分割が必要です。'), '输入最长 40 秒音频块；输出转写文本。': ('Input: audio chunks up to 40 seconds. Output: transcript text.', '最大40秒の音声区間を入力し、文字起こしテキストを出力します。'), 'FireRedASR2-LLM 官方 Hugging Face Model Card。': ('FireRedASR2-LLM official Hugging Face model card.', 'FireRedASR2-LLM公式Hugging Faceモデルカード。'), '20+ 中文方言/口音': ('20+ Chinese dialects and accents', '20以上の中国語方言・アクセント'), '语音、歌唱、中英混说': ('Speech, singing and Chinese-English code switching', '発話、歌唱、中国語と英語の混在'), '支持语音与歌唱': ('Speech and singing', '発話と歌唱に対応'), '歌唱': ('Singing', '歌唱'), 'FireRedASR2 官方 Model Card 汇总': ('Official checkpoint evaluation; see the source for the exact setup.', 'FireRedASR2公式モデルカードの集計'), '官方准确度表未声明硬件': ('Not stated in directly comparable form', '公式精度表にハードウェアの記載なし'), '官方 Model Card（revision 2c5e0f4）': ('Official source reviewed 2026-09-18', '公式モデルカード（revision 2c5e0f4）'), '官方示例返回值；不是统一批量 Benchmark': ('Official checkpoint evaluation; see the source for the exact setup.', '公式サンプルの出力値であり、統一条件のバッチベンチマークではありません'), '官方示例未声明': ('Not stated in directly comparable form', '公式サンプルに記載なし'), '两项 CER 来自同一官方 Model Card 表。RTF 0.0681 来自 hello_zh / hello_en 样例输出，硬件未声明，因此只按官方示例展示，不用于跨模型精确比较。': ('CER values come from the official model card; no cross-hardware speed comparison is implied.', '2つのCERは同じ公式モデルカードの表から引用しています。RTF 0.0681はhello_zh / hello_enのサンプル出力で、ハードウェアは未記載のため、モデル間の厳密な比較には使用しません。'), '官方权重文件约 17.57 GiB；独立 .venv-firered-llm Runtime。已在 RTX 5070 Ti 16 GB 上通过 20 秒中文及中英混合 fixture；推理时显存接近满载。': ('About 17.57 GiB of required files and an isolated .venv-firered-llm runtime.', '公式重みは約17.57 GiBで、独立した.venv-firered-llm環境を使用します。RTX 5070 Ti 16 GBで20秒の中国語・中英混在テストを通過しましたが、推論時のVRAMはほぼ上限に達します。'), '高级主力转写候选': ('Advanced primary transcription candidate', '上級者向け主文字起こし候補'), '中文普通话 4 集均值同表最佳（CER 2.89%）；速度暂无同组数据，本机未实测。': ('Card scores are same-group relative indices from audited comparison tables; missing groups stay unscored.', '普通話4データセット平均で同一表の最高値（CER 2.89%）。同条件の速度データはなく、手元のPCでは未測定です。'), '中文、英文、粤语与方言场景的轻量主力转写候选。': ('Compact primary transcription candidate for Chinese, English, Cantonese and dialects.', '中国語、英語、広東語、方言向けの軽量な主文字起こし候補。'), '作为高级用户可选的主力转写模型，通过独立 GLM Adapter 运行，不改变默认 Pipeline。': ('Runs through an isolated GLM adapter without changing the default pipeline.', '上級者向けの主文字起こしモデルで、独立したGLM Adapterを通して実行します。既定の処理構成は変えません。'), '官方描述为 1.5B 参数语音识别模型，使用 Transformers 的 GLM-ASR 条件生成架构。': ('Officially described as a 1.5B GLM-ASR conditional-generation model.', '公式には1.5Bパラメーターの音声認識モデルと記載され、TransformersのGLM-ASR条件付き生成を使用します。'), '面向粤语、方言、低音量和安静语音优化，并覆盖 17 种高可用语言。': ('Optimized for Cantonese, dialects and quiet or low-volume speech across 17 high-usability languages.', '広東語、方言、小音量・静かな発話向けに最適化され、17言語を高い実用性でサポートします。'), '官方当前要求 Transformers 源码/5.x 路径，与主环境锁定版本不兼容，必须隔离。': ('The current official path requires Transformers source / 5.x and must stay outside the main environment.', '現在の公式要件はTransformersのソース版または5.xで、メイン環境の固定バージョンと互換性がないため、環境を分離する必要があります。'), '输入音频；输出带规范文本的转写。': ('Input: audio. Output: normalized transcript text.', '音声を入力し、表記を整えた文字起こしを出力します。'), 'Z.ai GLM-ASR-Nano-2512 官方 Model Card。': ('Z.ai GLM-ASR-Nano-2512 official model card.', 'Z.ai GLM-ASR-Nano-2512公式モデルカード。'), '1.5B 官方描述；HF metadata 2,257,843,200': ('1.5B official description; 2,257,843,200 in HF safetensors metadata', '公式記載は1.5B、HF metadataは2,257,843,200'), '其它官方支持语言': ('Other officially supported languages', 'その他の公式対応言語'), '粤语与其它方言优化': ('Optimized for Cantonese and other dialects', '広東語とその他の方言に最適化'), '语音，包含低音量/安静语音': ('Speech including quiet and low-volume speech', '小音量・静かな発話を含む音声'), 'Transformers 5.x / SGLang（规划）': ('Transformers 5.x / planned SGLang support', 'Transformers 5.x / SGLang（予定）'), '低音量语音': ('Quiet speech', '小音量の発話'), '官方仓库汇总；与 OpenASR 不是同一评测': ('Official checkpoint evaluation; see the source for the exact setup.', '公式リポジトリの集計。OpenASRとは別の評価'), '官方摘要未声明': ('Not stated in directly comparable form', '公式概要に記載なし'), '官方 Model Card（revision 61ba4e0）': ('Official source reviewed 2026-09-18', '公式モデルカード（revision 61ba4e0）'), 'OpenASR leaderboard 评测': ('Official checkpoint evaluation; see the source for the exact setup.', 'OpenASR leaderboard評価'), 'OpenASR 条件见评测 YAML': ('Not stated in directly comparable form', 'OpenASRの条件は評価YAMLを参照'), '官方仓库 .eval_results': ('Official source reviewed 2026-09-18', '公式リポジトリの.eval_results'), 'Official Repo Benchmark 与 Hugging Face OpenASR 是两套来源，页面分行展示。官方正文称 1.5B，HF safetensors metadata 当前统计 2,257,843,200 parameters，两者原样并列，不擅自改写。': ('The official repository benchmark and Hugging Face OpenASR evaluation are separate sources.', '公式リポジトリのベンチマークとHugging Face OpenASRは別の出典として表示します。本文の1.5BとHF safetensors metadataの2,257,843,200パラメーターは、元の値を変更せず併記します。'), '官方仓库必需文件约 4.21 GiB；独立 .venv-glm-asr Runtime，不升级 .venv-main。': ('About 4.21 GiB of required files and an isolated .venv-glm-asr runtime.', '公式リポジトリの必須ファイルは約4.21 GiB。独立した.venv-glm-asr環境を使用し、.venv-mainは更新しません。'), '英语 OpenASR 榜单口径 Mean WER 7.03%（官方卡自报）；中文无同表数据，不做跨场景推断。': ('Card scores are same-group relative indices from audited comparison tables; missing groups stay unscored.', '英語OpenASR基準のMean WERは7.03%（公式カードの自己申告）。中国語の同一表データはなく、他の用途への推定には使用しません。'), 'English 专用的高吞吐主力转写候选。': ('High-throughput English-only primary transcription candidate.', '英語専用の高スループット主文字起こし候補。'), '只用于官方支持的 English ASR 场景，通过独立 NVIDIA NeMo Runtime 运行。': ('Runs only for supported English ASR scenarios in an isolated NVIDIA NeMo runtime.', '公式対応の英語ASRにのみ使用し、独立したNVIDIA NeMo環境で実行します。'), 'Speech-Augmented Language Model，组合 FastConformer speech encoder 与 Qwen language model。': ('A FastConformer plus Qwen Speech-Augmented Language Model.', 'FastConformer音声エンコーダーとQwen言語モデルを組み合わせたSpeech-Augmented Language Modelです。'), '英文 ASR 支持标点和大小写，官方 OpenASR 表给出高 RTFx。': ('English ASR with punctuation and capitalization and a high official OpenASR RTFx.', '英語ASRで句読点と大文字・小文字に対応し、公式OpenASR表では高いRTFxを示しています。'), '仅可靠支持 English；训练最大音频长度 40 秒，长输入精度可能下降；NeMo 依赖较重。': ('English only; maximum training audio duration was 40 seconds and NeMo is a heavy dependency.', '信頼できる対応言語は英語のみ。学習時の最大音声長は40秒で、長い入力では精度が低下する場合があります。NeMoの依存関係も大きめです。'), '输入 English 音频块；输出带标点和大小写的英文文本。': ('Input: English audio chunks. Output: punctuated and capitalized English text.', '英語音声の区間を入力し、句読点と大文字・小文字を含む英文を出力します。'), 'NVIDIA Canary-Qwen-2.5B 官方 Model Card。': ('NVIDIA Canary-Qwen-2.5B official model card.', 'NVIDIA Canary-Qwen-2.5B公式モデルカード。'), '不支持多语言场景': ('Not intended for multilingual use', '多言語処理には非対応'), 'NVIDIA A100（官方 Model Card）': ('Not stated in directly comparable form', 'NVIDIA A100（公式モデルカード）'), '官方 Model Card（revision b1469e1）': ('Official source reviewed 2026-09-18', '公式モデルカード（revision b1469e1）'), '官方 OpenASR 表': ('Official checkpoint evaluation; see the source for the exact setup.', '公式OpenASR表'), '英语成绩仅适用于官方支持的 English ASR。官方卡正文称 2.5B、HF 元数据统计约 3B，两者原样并列；推理验证环境含 A6000/A100/RTX 5090。': ('Reference scores apply only to supported English ASR scenarios.', '英語の成績は公式対応の英語ASRにのみ適用されます。公式本文の2.5BとHF metadataの約3Bをそのまま併記します。推論検証環境にはA6000/A100/RTX 5090が含まれます。'), '官方权重约 4.77 GiB；独立 .venv-canary-qwen NeMo Runtime，不向主 UI 环境安装 NeMo。': ('About 4.77 GiB of weights and an isolated .venv-canary-qwen runtime.', '公式重みは約4.77 GiB。独立した.venv-canary-qwen NeMo環境を使用し、メインUI環境にはNeMoをインストールしません。'), '高级 English 主力转写候选': ('Advanced primary transcription candidate', '上級者向け英語主文字起こし候補'), '英语 OpenASR 榜单 Mean WER 5.63% / RTFx 418（同表最佳）；仅限 English 场景，不代表多语言能力。': ('Card scores are same-group relative indices from audited comparison tables; missing groups stay unscored.', '英語OpenASRのMean WER 5.63% / RTFx 418（同一表で最高）。英語のみに適用され、多言語の能力は表しません。'), '为极广语言覆盖提供 1600+ 语言主力转写候选。': ('Primary transcription candidate for exceptionally broad 1600+ language coverage.', '1,600以上の言語を対象とする、広範な言語対応の主文字起こし候補。'), '作为高级多语言模型独立运行，不替换默认中文工作流。': ('An advanced multilingual option that does not replace the default Chinese workflow.', '上級者向け多言語モデルとして独立実行し、既定の中国語処理は置き換えません。'), 'Omnilingual ASR LLM 7B 支持可选语言条件，官方参数量 7,801,041,536。': ('A 7,801,041,536-parameter Omnilingual ASR LLM with optional language conditioning.', 'Omnilingual ASR LLM 7Bは任意の言語条件に対応し、公式パラメーター数は7,801,041,536です。'), '覆盖 1600+ 语言，适合其它模型未覆盖的低资源语言。': ('Covers more than 1600 languages, including many low-resource languages.', '1,600以上の言語に対応し、他のモデルが扱わない低リソース言語に適しています。'), '模型约 30 GiB，BF16 推理约需 17 GiB 显存；官方 RTF 接近实时，不适合低显存机器。': ('Roughly 30 GiB on disk and about 17 GiB BF16 VRAM; official speed is near real time.', 'モデルは約30 GiBで、BF16推論には約17 GiBのVRAMが必要です。公式RTFはリアルタイムに近く、VRAMの少ないPCには適しません。'), '输入音频与可选 language conditioning；输出对应语言文字。': ('Input: audio with optional language conditioning. Output: transcript text.', '音声と任意の言語条件を入力し、対象言語のテキストを出力します。'), 'Meta Omnilingual ASR 官方 Model Card 与论文。': ('Meta Omnilingual ASR official model card and paper.', 'Meta Omnilingual ASR公式モデルカードと論文。'), '完整语言 ID 由官方运行库提供': ('The complete language ID list is provided by the official runtime', '言語IDの完全な一覧は公式ランタイムが提供'), '随语言覆盖；官方未单列统一方言数': ('Covered within the language inventory; no unified dialect count', '対応言語に依存。公式には統一した方言数の記載なし'), '可选语言条件': ('Language conditioning', '任意の言語条件'), '低资源语言': ('Low-resource languages', '低リソース言語'), '官方 Model Card（revision 4b0bada）': ('Official source reviewed 2026-09-18', '公式モデルカード（revision 4b0bada）'), '官方 RTF 条件为 A100、batch 1、30 秒音频、BF16；不能外推为其它 GPU 的速度。': ('Official RTF uses an A100, batch 1, 30-second audio and BF16.', '公式RTFはA100、batch 1、30秒音声、BF16での値です。他のGPUの速度には換算できません。'), '官方 Download Size 30.0 GiB；HF 必需文件实测 29.06 GiB；BF16 VRAM 约 17 GiB。独立 .venv-omni-asr Runtime。': ('29.06 GiB of required HF files; official download size 30.0 GiB; isolated .venv-omni-asr runtime.', '公式Download Sizeは30.0 GiB、HF必須ファイルの実測は29.06 GiB、BF16のVRAM目安は17 GiBです。独立した.venv-omni-asr環境を使用します。'), '高级多语言主力转写候选': ('Advanced primary transcription candidate', '上級者向け多言語主文字起こし候補'), '官方模型卡未提供可比准确率表（未找到可核实数据）；RTF 0.092（A100/BF16/batch1/30s）为官方参考。': ('Card scores are same-group relative indices from audited comparison tables; missing groups stay unscored.', '公式カードには比較可能な精度表がなく、検証可能なデータは見つかっていません。RTF 0.092（A100/BF16/batch1/30s）は公式参考値です。'), '免下载的 Qwen3-ASR-Flash 在线转写。': ('Hosted transcription without a local model download.', 'ダウンロード不要のQwen3-ASR-Flashオンライン文字起こし。'), '在 2ByteASR 中作为在线文字复核来源，按短音频块返回独立文字；不提供本地模型资产，也不替代 MOSS 的说话人骨架。': ('Provides an optional online transcription or review source through DashScope.', '2ByteASRでは短い音声区間ごとに独立したテキストを返すオンライン確認用です。ローカルモデルを提供せず、MOSSの話者情報は置き換えません。'), '通过阿里云百炼 DashScope 多模态语音接口调用托管模型。底层推理、扩缩容与模型更新由服务商管理，客户端只提交音频并读取转写结果。': ('Audio is sent to the configured hosted ASR API; the server-side model can change independently of this application.', 'Alibaba CloudのDashScopeマルチモーダル音声APIでホストされたモデルを呼び出します。推論、拡張、モデル更新はサービス側が管理し、クライアントは音声を送信して結果を取得します。'), '无需下载和占用本地显存，配置密钥后可快速开始。': ('Fast setup and no local model storage.', 'ダウンロードとローカルVRAMが不要で、APIキーの設定後すぐに開始できます。'), '依赖网络、账户额度、服务可达性与云端模型版本；数据处理受服务条款约束。': ("Requires network access, a key, quota and acceptance of the provider's data policy.", 'ネットワーク、利用枠、サービスへの接続、モデルのバージョンに依存します。データ処理にはサービス規約が適用されます。'), '上传分块音频；返回在线转写文字。': ('Input: uploaded audio. Output: hosted transcription text.', '分割音声をアップロードし、オンライン文字起こしを取得します。'), '阿里云百炼 Qwen 语音识别官方文档。': ('Alibaba Cloud DashScope Qwen speech recognition documentation.', 'Alibaba Cloud DashScope Qwen音声認識の公式ドキュメント。'), '云服务未公开': ('Not published for the hosted service', 'クラウドサービスでは非公開'), '服务端模型可变': ('Hosted model may change', 'サーバー側モデルは変更される場合あり'), '托管 ASR 服务；底层参数未公开': ('Hosted ASR service; server architecture is not public', 'ホスト型ASRサービス。内部パラメーターは非公開'), '以当前服务文档为准': ('See current service documentation', '現在のサービスドキュメントを参照'), '在线音频转写': ('Hosted audio transcription', 'オンライン音声文字起こし'), '阿里云服务条款': ('Alibaba Cloud service terms', 'Alibaba Cloudサービス規約'), '官方未提供独立开源仓库': ('No separate open-source repository', '独立した公式オープンソースリポジトリなし'), '免下载': ('No download', 'ダウンロード不要'), '在线转写': ('Hosted ASR', 'オンライン文字起こし'), '低本地占用': ('Low local resource use', 'ローカル負荷が小さい'), '云服务文档未提供一组可与本地模型统一条件横向比较的公开数值；服务版本可能随平台更新。': ('No fixed public benchmark is directly comparable with the local checkpoints on this page.', 'サービスの資料にはローカルモデルと同条件で比較できる公開数値がありません。サービスのバージョンは更新される場合があります。'), '官方要求可用的 DashScope 账户、API Key 与网络；2ByteASR 本机无需模型显存，但需要稳定上传带宽。': ('Requires a DashScope key, quota and network access.', '利用可能なDashScopeアカウント、APIキー、ネットワークが必要です。2ByteASR側にモデル用VRAMは不要ですが、安定したアップロード帯域が必要です。'), '在线文字复核': ('Online review', 'オンラインテキスト確認'), '免下载且启动快，适合本地资源不足时补充一份在线文字证据。': ('Fast setup and no local model storage.', 'ダウンロード不要で開始が早く、ローカル資源が不足している場合の独立した照合に適しています。'), '通过 GroqCloud 调用 Whisper large-v3-turbo。': ('Hosted Whisper transcription through GroqCloud.', 'GroqCloud経由でWhisper large-v3-turboを呼び出します。'), '在 2ByteASR 中作为在线多语种复核来源，按短块提供独立转写；不参与本地说话人区分。': ('Provides an optional fast online text-review source.', '2ByteASRでは短い区間の独立した文字起こしを返すオンライン多言語確認用です。ローカルの話者分離には参加しません。'), '使用 OpenAI 风格 audio/transcriptions 协议，把音频发送到 Groq 托管的 Whisper large-v3-turbo；模型仍是编码器-解码器 Transformer，推理由 GroqCloud 执行。': ('Uses the OpenAI-compatible transcription protocol with a Groq-hosted Whisper checkpoint.', 'OpenAI形式のaudio/transcriptionsで、Groq上のWhisper large-v3-turboに音声を送信します。モデルはencoder-decoder Transformerで、推論はGroqCloudが実行します。'), '本地零模型占用，服务侧推理速度取向明显。': ('Low local resource use and fast hosted inference.', 'ローカルにモデルを置く必要がなく、サービス側の推論速度を重視しています。'), '依赖境外网络、Groq 账户额度和服务支持的文件/时长限制。': ('Requires network access, a Groq key and available quota.', '海外サービスへの接続、Groqの利用枠、ファイル・音声長の制限に依存します。'), '上传音频块；返回多语言转写文字。': ('Input: uploaded audio blocks. Output: hosted transcript text.', '音声区間をアップロードし、多言語の文字起こしを取得します。'), 'GroqCloud Speech-to-Text 官方文档与 OpenAI Whisper 官方模型。': ('GroqCloud Speech-to-Text documentation and the official OpenAI Whisper model.', 'GroqCloud Speech-to-Text公式ドキュメントとOpenAI Whisper公式モデル。'), 'Groq（托管）/ OpenAI（模型）': ('Groq (hosting) / OpenAI (model)', 'Groq（ホスティング）/ OpenAI（モデル）'), '809M（模型）': ('809M model', '809M（モデル）'), '取决于 Groq 当前托管的 Whisper checkpoint': ('Depends on the Whisper checkpoint currently hosted by Groq', 'Groqが現在ホストするWhisperチェックポイントに依存'), '服务文档未单列': ('Not listed by the service', 'サービスドキュメントに個別の記載なし'), 'Groq 服务条款 / Whisper MIT': ('Groq service terms / Whisper MIT', 'Groqサービス規約 / Whisper MIT'), '在线加速': ('Hosted Whisper', 'オンライン高速処理'), 'Groq 官方页面强调服务吞吐与延迟，但当前 metadata 没有找到与其它模型统一条件的公开准确率数值，因此不转写营销数字。': ('Provider speed claims are not a same-device benchmark against local 2ByteASR models.', 'Groqの公式ページはスループットと遅延を強調していますが、この資料には他モデルと同条件の公開精度値が見つかっていないため、宣伝数値は掲載しません。'), '需要 Groq API Key、额度和可用网络；本机不占模型显存。': ('Requires a Groq API key, quota and reachable service.', 'Groq APIキー、利用枠、ネットワークが必要です。ローカルのモデル用VRAMは使用しません。'), '适合已有 Groq 额度、希望减少本地模型占用的多语种复核。': ('Low local resource use and fast hosted inference.', 'Groqの利用枠があり、ローカルモデルの負荷を減らしたい場合の多言語確認に適しています。'), '通过 OpenAI 音频转写接口提供在线复核。': ('Configurable OpenAI speech-to-text review source.', 'OpenAIの音声文字起こしAPIでオンライン確認を行います。'), '在 2ByteASR 中作为可配置在线文字证据，对分块音频返回独立转写；不会替代主时间轴和说话人流程。': ('Adds an optional independent hosted transcript for users with an OpenAI account.', '2ByteASRでは分割音声から独立した文字起こしを取得する、設定可能なオンライン照合用です。主要な時刻調整と話者処理は置き換えません。'), '使用 OpenAI audio/transcriptions 协议调用账户可用的转写模型。模型实现与版本由服务端管理，2ByteASR 只维护请求、结果映射和失败处理。': ('Uploads audio through the official speech-to-text API using the selected hosted model.', 'OpenAI audio/transcriptionsでアカウントが利用できるモデルを呼び出します。実装とバージョンはサービス側が管理し、2ByteASRはリクエスト、結果の対応付け、失敗処理を担当します。'), '无需本地下载，通用多语种能力和上下文提示适合复核。': ('General hosted transcription with context support where the selected model provides it.', 'ローカルダウンロードが不要で、多言語対応と文脈ヒントを確認に活用できます。'), '依赖境外服务、账户额度、隐私策略和当前模型可用性。': ('Model capability, pricing and availability depend on the configured service model.', '海外サービス、利用枠、プライバシー方針、現在のモデル提供状況に依存します。'), '上传音频块；返回在线转写文字。': ('Input: uploaded audio blocks. Output: hosted transcript text.', '音声区間をアップロードし、オンライン文字起こしを取得します。'), 'OpenAI Speech-to-Text 官方文档。': ('OpenAI Speech-to-Text documentation.', 'OpenAI Speech-to-Text公式ドキュメント。'), 'Transcribe API（模型可配置）': ('Transcription API (configurable model)', '文字起こしAPI（モデルを設定可能）'), '服务未公开': ('Not public for the hosted service', 'サービスでは非公開'), '服务端模型可配置': ('Hosted model is configurable', 'サーバー側モデルを設定可能'), '托管语音转写模型': ('Hosted transcription model', 'ホスト型音声文字起こしモデル'), '以当前模型文档为准': ('See current model documentation', '現在のモデルドキュメントを参照'), 'OpenAI 服务条款': ('OpenAI service terms', 'OpenAIサービス規約'), '官方未提供服务端模型仓库': ('No repository for the hosted server model', 'サーバーモデルの公式リポジトリなし'), '上下文提示': ('Context prompt', '文脈ヒント'), '官方文档未提供一个与本页其它本地模型同条件、可直接比较的逐数据集数值表。': ('No fixed model and same-condition public table is available for comparison here.', '公式資料には、このページの他のローカルモデルと同条件で直接比較できるデータセット別の数値表がありません。'), '需要 OpenAI API Key、账户额度与可用网络；本机不占模型显存。': ('Requires an OpenAI API key, quota and network access.', 'OpenAI APIキー、利用枠、ネットワークが必要です。ローカルのモデル用VRAMは使用しません。'), '适合已有 OpenAI API 的用户增加一份通用多语种文字证据。': ('General hosted transcription with context support where the selected model provides it.', 'OpenAI APIを利用中で、汎用の多言語認識結果を追加したい場合に適しています。'), '连接用户自备的 OpenAI 兼容音频转写服务。': ('Connect a user-provided OpenAI-compatible transcription service.', 'ユーザーが用意したOpenAI互換音声文字起こしサービスに接続します。'), '在 2ByteASR 中只承担可配置在线/自托管文字复核入口，具体能力取决于用户选择的服务和模型。': ('Acts only as a configurable online or self-hosted review endpoint.', '2ByteASRでは設定可能なオンライン・自己ホスト型のテキスト確認入口として使用します。機能は選択したサービスとモデルに依存します。'), '按 OpenAI audio/transcriptions 兼容协议提交音频、模型名和鉴权信息；该入口没有固定模型，因此无法声明统一架构或 Benchmark。': ('Submits audio, model name and authentication through the compatible audio/transcriptions protocol.', 'OpenAI audio/transcriptions互換形式で音声、モデル名、認証情報を送信します。固定モデルがないため、共通のアーキテクチャやベンチマークは示せません。'), '服务商、模型名和地址均可配置，也可连接自托管服务。': ('Provider, endpoint and model name are user controlled.', 'サービス、モデル名、アドレスを設定でき、自己ホスト型にも接続できます。'), '兼容性、准确率、隐私、费用和稳定性均由目标服务决定；需要用户自行核对。': ('Accuracy, privacy, price and reliability all depend on the configured service.', '互換性、精度、プライバシー、料金、安定性は接続先サービスによって異なるため、ユーザー自身で確認してください。'), '上传音频块；读取兼容服务返回的转写文字。': ('Input: uploaded audio. Output: compatible service response.', '音声区間をアップロードし、互換サービスから文字起こしを取得します。'), '用户配置的服务文档。': ('Documentation for the user-configured service.', 'ユーザーが設定したサービスのドキュメント。'), '用户配置': ('User configured', 'ユーザー設定'), '取决于模型': ('Model dependent', 'モデルによる'), '无固定 checkpoint': ('No fixed checkpoint', '固定チェックポイントなし'), '取决于服务': ('Service dependent', 'サービスによる'), 'OpenAI 兼容 audio/transcriptions API': ('OpenAI-compatible audio/transcriptions API', 'OpenAI互換audio/transcriptions API'), '无统一官方仓库': ('No single official repository', '共通の公式リポジトリなし'), '用户配置 / User configured': ('User configured', 'ユーザー設定'), '自定义地址': ('Custom endpoint', 'カスタムアドレス'), '自定义模型': ('Custom model', 'カスタムモデル'), '在线或自托管': ('Online or self-hosted', 'オンラインまたは自己ホスト型'), '没有固定模型或统一官方来源，无法提供可核对的公共 Benchmark；请以所配置服务的官方资料为准。': ('There is no fixed checkpoint or unified official benchmark.', '固定モデルや共通の公式出典がないため、検証可能な公開ベンチマークは提示できません。設定したサービスの公式資料を参照してください。'), '需要兼容服务、模型名、URL 和密钥；硬件与网络要求取决于目标服务。': ('Requires a compatible endpoint, model name and key; hardware and networking are service dependent.', '互換サービス、モデル名、URL、APIキーが必要です。ハードウェアとネットワークの要件は接続先によって異なります。'), '自定义文字复核': ('Custom review', 'カスタムテキスト確認'), '为已有第三方或自托管 ASR 的用户保留兼容入口，不对未知模型作统一评分承诺。': ('Provider, endpoint and model name are user controlled.', '外部または自己ホスト型ASRへの互換接続を提供します。未知のモデルに一律のスコアは付けません。'), '转写准确度': ('Transcription accuracy', '文字起こし精度'), '语音识别': ('Speech Recognition', '音声認識'), '字幕文本': ('Subtitle text', '字幕テキスト'), '时间对齐': ('Time alignment', '時刻アラインメント'), '音频 + 已有文本': ('Audio + existing text', '音声と既存テキスト'), '字 / 词级时间位置': ('Character / word timestamps', '文字・単語単位の時刻'), '说话人分析': ('Speaker analysis', '話者解析'), '说话人片段': ('Speaker segments', '話者区間'), '文本复核': ('Text Review', 'テキスト確認'), '文本复核能力': ('Text review capability', 'テキスト確認能力'), '已有文本': ('Existing text', '既存テキスト'), '修订文本': ('Revised text', '修正後のテキスト'), '翻译': ('Translation', '翻訳'), '翻译质量': ('Translation quality', '翻訳品質'), '译文': ('Translated text', '翻訳文'), '辅助模型': ('Auxiliary model', '補助モデル'), '任务参考': ('Task reference', 'タスクの参考指標'), '见技术说明': ('See technical details', '技術説明を参照'), '辅助处理': ('Auxiliary processing', '補助処理'), '多人语音转写 + 说话人区分，适合直播和多人录音。': ('Multi-speaker transcription and speaker diarization for livestreams and group recordings.', '複数話者の文字起こしと話者分離。配信や複数人の録音に適しています。'), '长音频、直播和多人录音': ('Long audio, livestreams and group recordings', '長時間音声、配信、複数人の録音'), '说话人标签不等于真实姓名': ('Speaker labels do not identify real names', '話者ラベルは実名を表しません'), '先生成文字骨架、分段和说话人证据。': ('First creates the text backbone, segments and speaker evidence.', 'まずテキストの骨格、区間、話者情報を生成します。'), '中文 / 方言高精度转写，并支持细粒度时间轴。': ('High-accuracy Chinese and dialect transcription with fine-grained timestamps.', '中国語・方言を高精度に文字起こしし、細かな時刻調整にも対応します。'), '中文、方言及需要细粒度时间戳的字幕': ('Chinese, dialects and subtitles requiring fine-grained timestamps', '中国語、方言、細かなタイムスタンプが必要な字幕'), '既可独立转写，也可在组合流程中提供字级时间轴。': ('Works as standalone ASR or provides character timestamps in a combined pipeline.', '単独で文字起こしでき、組み合わせた処理では文字単位の時刻を提供します。'), '字级时间轴': ('Character timestamps', '文字単位の時刻'), '多语言高精度转写，适合通用字幕识别。': ('High-accuracy multilingual transcription for general subtitles.', '高精度な多言語文字起こし。一般的な字幕認識に適しています。'), '通用字幕、多语言和专名复核': ('General subtitles, multilingual content and proper-name review', '一般的な字幕、多言語、固有名詞の確認'), '可独立转写；复核阶段重新听音频，提供独立文字证据。': ('Works as standalone ASR; during review it listens again to provide independent text evidence.', '単独で文字起こしできます。確認段階では音声を再認識して独立したテキストを提供します。'), '高精度中文 / 方言转写，质量优先但资源占用更高。': ('High-accuracy Chinese and dialect transcription, prioritizing quality with higher resource use.', '中国語・方言の高精度文字起こし。品質を重視するため、リソース使用量は多めです。'), '中文和方言的质量优先转写': ('Quality-first Chinese and dialect transcription', '中国語・方言の品質重視の文字起こし'), '中文、粤语及英语转写，适合低音量语音素材。': ('Chinese, Cantonese and English transcription, suited to quiet speech.', '中国語、広東語、英語の文字起こし。小音量の音声に適しています。'), '中文、粤语和低音量语音': ('Chinese, Cantonese and quiet speech', '中国語、広東語、小音量の音声'), '英语高吞吐转写，适合批量处理英语素材。': ('High-throughput English transcription for batch processing.', '高スループットの英語文字起こし。英語素材の一括処理に適しています。'), '英语素材批量转写': ('Batch transcription of English media', '英語素材の一括文字起こし'), '不支持中文': ('Chinese not supported', '中国語には非対応'), '高吞吐': ('High throughput', '高スループット'), '超多语言覆盖，适合小语种和跨语言素材。': ('Extensive language coverage for less common languages and multilingual media.', '幅広い言語に対応し、少数言語や言語混在素材に適しています。'), '小语种及跨语言素材': ('Less common languages and multilingual media', '少数言語・複数言語の素材'), '上游 fairseq2 不支持原生 Windows；当前仅可下载权重': ('Upstream fairseq2 does not support native Windows; only weight downloads are currently available', '上流のfairseq2はネイティブWindowsに非対応。現在は重みのダウンロードのみ可能'), 'Windows 仅权重': ('Windows: weights only', 'Windowsは重みのみ'), '轻量多语言转写，低配置设备也能使用。': ('Lightweight multilingual transcription, including on lower-spec computers.', '軽量な多言語文字起こし。低スペックのPCでも使用できます。'), '低配置设备上的常见语言转写': ('Common-language transcription on lower-spec computers', '低スペックPCでの一般的な言語の文字起こし'), 'CPU 可用': ('CPU supported', 'CPU対応'), '中文快速转写，并支持时间轴。': ('Fast Chinese transcription with timestamp support.', '中国語の高速文字起こしと時刻調整に対応します。'), '中文快速转写和热词识别': ('Fast Chinese transcription and hotword recognition', '中国語の高速文字起こしとホットワード認識'), '多语言通用转写，适合多种语言的视频字幕。': ('General multilingual transcription for video subtitles in many languages.', '多言語の汎用文字起こし。さまざまな言語の動画字幕に適しています。'), '中文方言与多语言转写，可提供独立文字复核证据。': ('Chinese dialect and multilingual transcription with independent text review evidence.', '中国語方言と多言語の文字起こし。独立したテキスト確認の根拠を提供できます。'), '已有字幕的高精度字词时间轴对齐。': ('High-precision character and word alignment for existing subtitles.', '既存字幕の文字・単語を高精度に時刻へ整列します。'), 'ASR 转写与纠错后的最终时间轴精修': ('Final timing refinement after ASR and text corrections', '音声認識とテキスト修正後の最終的なタイミング調整'), '不能独立转写，也不负责识别或纠正字幕内容': ('Cannot transcribe independently or recognize or correct subtitle content', '単独で文字起こしできず、字幕内容の認識・修正も行いません'), '先由 ASR 得到文字，再根据音频定位字词。': ('ASR first produces the text, then audio is used to locate each character and word.', 'まずASRでテキストを生成し、音声に合わせて文字・単語の時刻を求めます。'), '云端多语言转写，适合免安装的字幕识别。': ('Cloud multilingual transcription without installing a local model.', 'クラウド多言語文字起こし。モデルをインストールせずに字幕を認識できます。'), '云端语音转写，适合中文素材快速识别与复核。': ('Cloud speech recognition for fast Chinese transcription and review.', 'クラウド音声認識。中国語素材の高速な文字起こしと確認に適しています。'), '云端加速转写，适合多语言字幕与短块复核。': ('Accelerated cloud transcription for multilingual subtitles and short-chunk review.', 'クラウドの高速文字起こし。多言語字幕や短い区間の確認に適しています。'), '通用云端语音转写，适合多语言字幕识别。': ('General cloud transcription for multilingual subtitles.', '汎用クラウド文字起こし。多言語の字幕認識に適しています。'), '云端转写并提供字级时间戳，适合细化字幕时间轴。': ('Cloud transcription with character timestamps for precise subtitle timing.', '文字単位のタイムスタンプを返すクラウド文字起こし。字幕の時刻調整に適しています。'), '录音文件转写，提供词级时间戳与说话人信息。': ('Recorded-file transcription with word timestamps and speaker information.', '録音ファイルの文字起こし。単語時刻と話者情報を提供します。'), '连接自备语音转写服务，能力取决于配置型号。': ('Connect your own transcription service; capabilities depend on the configured model.', 'ユーザーの文字起こしサービスに接続します。機能は設定したモデルによって異なります。'), '评分仅在同类任务模型中用于相对比较；不同任务的 100 分不能横向比较，也不是正确率百分比。': ('Scores compare models within the same task. A score of 100 cannot be compared across tasks and is not a percentage of correct results.', 'スコアは同種タスクのモデル間の相対比較用です。異なるタスクの100点同士は比較できず、正解率の百分率でもありません。'), '速度指数越高越快，100 为参考目录最快档。公开数据的硬件与服务条件不同，实际速度以本机或当前服务为准。': ('A higher speed index is faster; 100 is the fastest tier in the reference catalog. Published hardware and service conditions differ, so actual speed depends on your computer or current service.', '速度指数は高いほど高速で、100は参考カタログの最速水準です。公開データはハードウェアやサービス条件が異なるため、実際の速度は手元のPCや現在のサービスで確認してください。'), '安装大小仅代表本地文件占用，不等同于模型能力或准确率。大小受参数量、权重精度、运行库和附属文件影响。': ('Installation size measures local file storage, not capability or accuracy. It depends on parameter count, weight precision, runtime libraries and supporting files.', 'インストール容量はローカルファイルの占有量であり、モデルの能力や精度ではありません。パラメーター数、重みの精度、ランタイム、付属ファイルによって変わります。')})

# Benchmark presentation, using the unchanged bundled evidence.
STRINGS.update({'FireRed 官方同表': ('FireRed official comparison table', 'FireRed公式比較表'),
 '普通话 4 集均值 CER 2.89%，该表最佳': ('Mandarin 4-set mean CER 2.89%, best in this table', '普通話4セット平均CER 2.89%、同一表で最高'),
 'FireRedASR2 官方 README 评测表：普通话 4 集（AISHELL-1/2+WenetSpeech net/meeting）均值 CER 2.89%（LLM），同表含 FireRed-AED 3.05 / Qwen3-ASR-1.7B 3.76 / Doubao 3.69 / Fun-ASR-7.7B(闭源) 4.16。sqrt 相对分=组内最佳 100。': ('FireRedASR2 '
                                                                                                                                                                                                 'README: '
                                                                                                                                                                                                 'Mandarin '
                                                                                                                                                                                                 'mean '
                                                                                                                                                                                                 'over '
                                                                                                                                                                                                 'AISHELL-1/2 '
                                                                                                                                                                                                 'and '
                                                                                                                                                                                                 'WenetSpeech '
                                                                                                                                                                                                 'net/meeting '
                                                                                                                                                                                                 'is '
                                                                                                                                                                                                 'CER '
                                                                                                                                                                                                 '2.89% '
                                                                                                                                                                                                 'for '
                                                                                                                                                                                                 'LLM. '
                                                                                                                                                                                                 'Same-table '
                                                                                                                                                                                                 'values: '
                                                                                                                                                                                                 'AED '
                                                                                                                                                                                                 '3.05, '
                                                                                                                                                                                                 'Qwen3-ASR-1.7B '
                                                                                                                                                                                                 '3.76, '
                                                                                                                                                                                                 'Doubao '
                                                                                                                                                                                                 '3.69, '
                                                                                                                                                                                                 'closed '
                                                                                                                                                                                                 'Fun-ASR-7.7B '
                                                                                                                                                                                                 '4.16. '
                                                                                                                                                                                                 'The '
                                                                                                                                                                                                 'square-root '
                                                                                                                                                                                                 'relative '
                                                                                                                                                                                                 'index '
                                                                                                                                                                                                 'gives '
                                                                                                                                                                                                 'the '
                                                                                                                                                                                                 'group '
                                                                                                                                                                                                 'best '
                                                                                                                                                                                                 '100.',
                                                                                                                                                                                                 'FireRedASR2 '
                                                                                                                                                                                                 'README：AISHELL-1/2とWenetSpeech '
                                                                                                                                                                                                 'net/meetingの普通話平均はLLMのCER '
                                                                                                                                                                                                 '2.89%。同一表：AED '
                                                                                                                                                                                                 '3.05、Qwen3-ASR-1.7B '
                                                                                                                                                                                                 '3.76、Doubao '
                                                                                                                                                                                                 '3.69、非公開Fun-ASR-7.7B '
                                                                                                                                                                                                 '4.16。平方根による相対指数で最高値を100とします。'),
 '方言 19 集均值 CER 11.55%，该表最佳': ('19-dialect mean CER 11.55%, best in this table', '19方言セット平均CER 11.55%、同一表で最高'),
 'FireRedASR2 官方表：19 个方言/口音公开集均值 CER 11.55%（LLM），同表 AED 11.67 / Qwen3 11.85 / Fun-ASR-7.7B 12.76 / Doubao 15.39。': ('FireRedASR2 '
                                                                                                                    'official '
                                                                                                                    'table: '
                                                                                                                    'LLM '
                                                                                                                    'mean '
                                                                                                                    'CER '
                                                                                                                    '11.55% '
                                                                                                                    'over '
                                                                                                                    '19 '
                                                                                                                    'public '
                                                                                                                    'dialect/accent '
                                                                                                                    'sets. '
                                                                                                                    'Same '
                                                                                                                    'table: '
                                                                                                                    'AED '
                                                                                                                    '11.67, '
                                                                                                                    'Qwen3 '
                                                                                                                    '11.85, '
                                                                                                                    'Fun-ASR-7.7B '
                                                                                                                    '12.76, '
                                                                                                                    'Doubao '
                                                                                                                    '15.39.',
                                                                                                                    'FireRedASR2公式表：19の公開方言・アクセントセットでLLM平均CER '
                                                                                                                    '11.55%。同一表：AED '
                                                                                                                    '11.67、Qwen3 '
                                                                                                                    '11.85、Fun-ASR-7.7B '
                                                                                                                    '12.76、Doubao '
                                                                                                                    '15.39。'),
 '英语无公开成绩': ('No published English results', '英語の公開成績なし'),
 '官方示例+档位估算': ('Official sample + tier estimate', '公式サンプルと水準推定'),
 '官方示例 RTF 0.0681；vLLM 服务化更快但无公开数值': ('Official sample RTF 0.0681; vLLM serving is faster but has no published value',
                                      '公式サンプルRTF 0.0681。vLLMサーバーは高速だが公開値なし'),
 'FireRedASR2-LLM 官方 hello 示例输出 RTF 0.0681（硬件未声明，非正式基准）；官方推荐 vLLM 服务化（PR #35727）但未公布吞吐。按自回归 LLM-ASR 档位估 25（区间 15-40）。8B+ 权重、17.57 GiB 下载。': ('FireRedASR2-LLM '
                                                                                                                                             'hello '
                                                                                                                                             'sample '
                                                                                                                                             'reports '
                                                                                                                                             'RTF '
                                                                                                                                             '0.0681, '
                                                                                                                                             'without '
                                                                                                                                             'hardware '
                                                                                                                                             'or '
                                                                                                                                             'a '
                                                                                                                                             'formal '
                                                                                                                                             'benchmark. '
                                                                                                                                             'vLLM '
                                                                                                                                             'serving '
                                                                                                                                             'is '
                                                                                                                                             'recommended '
                                                                                                                                             '(PR '
                                                                                                                                             '#35727), '
                                                                                                                                             'but '
                                                                                                                                             'throughput '
                                                                                                                                             'is '
                                                                                                                                             'unpublished. '
                                                                                                                                             'Estimated '
                                                                                                                                             'autoregressive '
                                                                                                                                             'LLM-ASR '
                                                                                                                                             'tier: '
                                                                                                                                             '25 '
                                                                                                                                             '(15–40). '
                                                                                                                                             'Weights: '
                                                                                                                                             '8B+; '
                                                                                                                                             'download: '
                                                                                                                                             '17.57 '
                                                                                                                                             'GiB.',
                                                                                                                                             'FireRedASR2-LLMのhelloサンプルはRTF '
                                                                                                                                             '0.0681で、ハードウェア未記載の非正式ベンチマークです。vLLMサーバーを推奨（PR '
                                                                                                                                             '#35727）するものの、スループットは未公開。自己回帰LLM-ASRの水準として25（15～40）と推定。8B以上、ダウンロード17.57 '
                                                                                                                                             'GiB。'),
 '普通话 4 集均值 CER 3.05%（同表第 2）': ('Mandarin 4-set mean CER 3.05%, second in this table', '普通話4セット平均CER 3.05%、同一表で2位'),
 'FireRedASR2-AED 官方表普通话 4 集均值 3.05%；sqrt(2.89/3.05)=97。': ('FireRedASR2-AED official Mandarin 4-set mean: 3.05%; '
                                                            'sqrt(2.89/3.05)=97.',
                                                            'FireRedASR2-AED公式の普通話4セット平均3.05%。sqrt(2.89/3.05)=97。'),
 '方言 19 集均值 CER 11.67%（同表第 2）': ('19-dialect mean CER 11.67%, second in this table', '19方言セット平均CER 11.67%、同一表で2位'),
 '方言 19 集均值 11.67%；sqrt(11.55/11.67)=99（与 Qwen3 11.85 同为 99，未取整 99.5 vs 98.7）。': ('19-dialect mean 11.67%; '
                                                                                  'sqrt(11.55/11.67)=99. Qwen3 at '
                                                                                  '11.85 also rounds to 99; unrounded '
                                                                                  'scores are 99.5 and 98.7.',
                                                                                  '19方言平均11.67%、sqrt(11.55/11.67)=99。Qwen3の11.85も丸めると99（丸め前99.5と98.7）。'),
 '官方示例+TensorRT 区间': ('Official sample + TensorRT range', '公式サンプルとTensorRTの範囲'),
 '示例 RTF 0.087（PyTorch）；TensorRT-LLM 官方加速 12.7x（H20）': ('Sample RTF 0.087 (PyTorch); official TensorRT-LLM speedup '
                                                        '12.7× on H20',
                                                        'サンプルRTF 0.087（PyTorch）、公式TensorRT-LLMはH20で12.7倍'),
 'AED 官方示例 RTF 0.0870（硬件未声明）；NVIDIA 贡献的 TensorRT-LLM 在 AISHELL-1 上 12.7x 加速（单张 H20）→ 约 RTF 0.0069。折算区间约 RTFx 12-145，取中低档 30。2ByteASR 本地走 PyTorch 路径。': ('AED '
                                                                                                                                                        'sample '
                                                                                                                                                        'RTF '
                                                                                                                                                        '0.0870 '
                                                                                                                                                        'has '
                                                                                                                                                        'unspecified '
                                                                                                                                                        'hardware. '
                                                                                                                                                        'NVIDIA '
                                                                                                                                                        'TensorRT-LLM '
                                                                                                                                                        'achieves '
                                                                                                                                                        '12.7× '
                                                                                                                                                        'on '
                                                                                                                                                        'AISHELL-1 '
                                                                                                                                                        'with '
                                                                                                                                                        'one '
                                                                                                                                                        'H20, '
                                                                                                                                                        'implying '
                                                                                                                                                        'about '
                                                                                                                                                        'RTF '
                                                                                                                                                        '0.0069. '
                                                                                                                                                        'Estimated '
                                                                                                                                                        'RTFx '
                                                                                                                                                        'range: '
                                                                                                                                                        '12–145; '
                                                                                                                                                        'conservative '
                                                                                                                                                        'tier: '
                                                                                                                                                        '30. '
                                                                                                                                                        '2ByteASR '
                                                                                                                                                        'runs '
                                                                                                                                                        'the '
                                                                                                                                                        'local '
                                                                                                                                                        'PyTorch '
                                                                                                                                                        'path.',
                                                                                                                                                        'AEDサンプルはRTF '
                                                                                                                                                        '0.0870、ハードウェア未記載。NVIDIAのTensorRT-LLMはH20 '
                                                                                                                                                        '1枚のAISHELL-1で12.7倍、換算RTF約0.0069。RTFxの推定範囲12～145から控えめな水準30を採用。2ByteASRのローカル実行はPyTorchです。'),
 '普通话 4 集均值 CER 3.76%（FireRed 复测 Qwen3-ASR-1.7B）': ('Mandarin 4-set mean CER 3.76% (FireRed retest of Qwen3-ASR-1.7B)',
                                                    '普通話4セット平均CER 3.76%（FireRedによるQwen3-ASR-1.7B再評価）'),
 'FireRed 官方表对 Qwen3-ASR-1.7B 的同管线复测：普通话均值 3.76%；sqrt(2.89/3.76)=88。Qwen 自家表中文集更优（WenetSpeech net 4.97 / Fleurs-zh 2.41 同表最佳）。': ('FireRed '
                                                                                                                                  'retests '
                                                                                                                                  'Qwen3-ASR-1.7B '
                                                                                                                                  'in '
                                                                                                                                  'the '
                                                                                                                                  'same '
                                                                                                                                  'pipeline: '
                                                                                                                                  'Mandarin '
                                                                                                                                  'mean '
                                                                                                                                  '3.76%; '
                                                                                                                                  'sqrt(2.89/3.76)=88. '
                                                                                                                                  "Qwen's "
                                                                                                                                  'own '
                                                                                                                                  'table '
                                                                                                                                  'has '
                                                                                                                                  'better '
                                                                                                                                  'Chinese '
                                                                                                                                  'results: '
                                                                                                                                  'WenetSpeech '
                                                                                                                                  'net '
                                                                                                                                  '4.97 '
                                                                                                                                  'and '
                                                                                                                                  'Fleurs-zh '
                                                                                                                                  '2.41, '
                                                                                                                                  'both '
                                                                                                                                  'table '
                                                                                                                                  'bests.',
                                                                                                                                  'FireRedの同じ手順によるQwen3-ASR-1.7B再評価は普通話平均3.76%、sqrt(2.89/3.76)=88。Qwen自社表はWenetSpeech '
                                                                                                                                  'net '
                                                                                                                                  '4.97、Fleurs-zh '
                                                                                                                                  '2.41で、ともに同一表の最高値です。'),
 '方言 19 集均值 CER 11.85%（同表第 3，与 AED 同为 99）': ('19-dialect mean CER 11.85%, third in the table, rounding to 99 like AED',
                                             '19方言平均CER 11.85%、同一表3位。AEDと同じ99に丸め'),
 '方言均值 11.85%；sqrt(11.55/11.85)=99。官方另列 22 种中文方言支持。': ('Dialect mean 11.85%; sqrt(11.55/11.85)=99. The official '
                                                       'documentation separately lists support for 22 Chinese '
                                                       'dialects.',
                                                       '方言平均11.85%、sqrt(11.55/11.85)=99。公式資料は別途22の中国語方言対応を記載しています。'),
 '跨榜校准（AA 统一尺度）': ('Cross-leaderboard calibration to AA', 'ランキング間のAA基準への較正'),
 'LibriSpeech clean WER 1.63%（Qwen 官方表）经 turbo 锚换算到 AA 尺度': ("LibriSpeech clean WER 1.63% from Qwen's table, "
                                                             'calibrated to AA using turbo',
                                                             'Qwen公式のLibriSpeech clean WER 1.63%をturbo基準でAAへ較正'),
 '统一到 AA 英語尺度：turbo 同模型跨榜 WER 比 7.83/4.6=1.70。Qwen3-ASR-1.7B LibriSpeech clean 1.63%（Qwen 官方表，与 AA 集不同）→ AA 等效约 2.8% → sqrt(2.0/2.8)×100≈84，考虑测试集差异取约 78。AA 榜单未收录 Qwen3-ASR。': ('AA '
                                                                                                                                                                                'English '
                                                                                                                                                                                'calibration '
                                                                                                                                                                                'uses '
                                                                                                                                                                                "turbo's "
                                                                                                                                                                                'cross-table '
                                                                                                                                                                                'WER '
                                                                                                                                                                                'ratio '
                                                                                                                                                                                '7.83/4.6=1.70. '
                                                                                                                                                                                'Qwen3-ASR-1.7B '
                                                                                                                                                                                'LibriSpeech '
                                                                                                                                                                                'clean '
                                                                                                                                                                                '1.63% '
                                                                                                                                                                                'implies '
                                                                                                                                                                                'about '
                                                                                                                                                                                '2.8% '
                                                                                                                                                                                'AA-equivalent, '
                                                                                                                                                                                'or '
                                                                                                                                                                                'sqrt(2.0/2.8)×100≈84. '
                                                                                                                                                                                'Adjusted '
                                                                                                                                                                                'to '
                                                                                                                                                                                'about '
                                                                                                                                                                                '78 '
                                                                                                                                                                                'for '
                                                                                                                                                                                'different '
                                                                                                                                                                                'test '
                                                                                                                                                                                'sets. '
                                                                                                                                                                                'AA '
                                                                                                                                                                                'does '
                                                                                                                                                                                'not '
                                                                                                                                                                                'list '
                                                                                                                                                                                'Qwen3-ASR.',
                                                                                                                                                                                'AA英語基準への較正はturboのWER比7.83/4.6=1.70を使用。Qwen3-ASR-1.7BのLibriSpeech '
                                                                                                                                                                                'clean '
                                                                                                                                                                                '1.63%はAA換算約2.8%、sqrt(2.0/2.8)×100≈84。テストセットの違いを考慮し約78とします。AAにはQwen3-ASRの掲載がありません。'),
 '同级类推估算': ('Estimate from comparable model tiers', '同水準モデルからの推定'),
 '1.7B 自回归 LLM-ASR；无官方 RTF': ('1.7B autoregressive LLM-ASR; no official RTF', '1.7B自己回帰LLM-ASR、公式RTFなし'),
 '官方未公布 RTF；按同级自回归 LLM-ASR（FireRed-LLM 示例 0.068 / MOSS H100 0.0197）档位估 30（区间 20-40）。vLLM 批量推理会更快。': ('No official RTF. '
                                                                                                     'Estimated tier '
                                                                                                     '30 (20–40) from '
                                                                                                     'comparable '
                                                                                                     'autoregressive '
                                                                                                     'LLM-ASR: '
                                                                                                     'FireRed-LLM '
                                                                                                     'sample 0.068 and '
                                                                                                     'MOSS H100 '
                                                                                                     '0.0197. vLLM '
                                                                                                     'batch inference '
                                                                                                     'can be faster.',
                                                                                                     '公式RTFは未公開。類似の自己回帰LLM-ASR（FireRed-LLMサンプル0.068、MOSS '
                                                                                                     'H100 '
                                                                                                     '0.0197）から30（20～40）と推定。vLLMのバッチ推論はより高速になります。'),
 'MOSS 官方同表': ('MOSS official comparison table', 'MOSS公式比較表'),
 'AISHELL-4 CER 14.84%，长音频多说话人同表最佳': ('AISHELL-4 CER 14.84%, best long-form multi-speaker result in the table',
                                      'AISHELL-4 CER 14.84%、長時間・複数話者の同一表で最高'),
 'MOSS-Transcribe-Diarize 官方表：AISHELL-4 14.84 / Alimeeting 24.86（同表最佳），对照 Gemini 3 Pro 22.75/26.75、Doubao 18.18/25.25、ElevenLabs 19.58/25.70、Gemini 2.5 Pro 42.70/27.43。': ('MOSS '
                                                                                                                                                                            'official '
                                                                                                                                                                            'table: '
                                                                                                                                                                            'AISHELL-4 '
                                                                                                                                                                            '14.84 '
                                                                                                                                                                            '/ '
                                                                                                                                                                            'Alimeeting '
                                                                                                                                                                            '24.86, '
                                                                                                                                                                            'both '
                                                                                                                                                                            'best. '
                                                                                                                                                                            'Comparisons: '
                                                                                                                                                                            'Gemini '
                                                                                                                                                                            '3 '
                                                                                                                                                                            'Pro '
                                                                                                                                                                            '22.75/26.75, '
                                                                                                                                                                            'Doubao '
                                                                                                                                                                            '18.18/25.25, '
                                                                                                                                                                            'ElevenLabs '
                                                                                                                                                                            '19.58/25.70, '
                                                                                                                                                                            'Gemini '
                                                                                                                                                                            '2.5 '
                                                                                                                                                                            'Pro '
                                                                                                                                                                            '42.70/27.43.',
                                                                                                                                                                            'MOSS公式表：AISHELL-4 '
                                                                                                                                                                            '14.84 '
                                                                                                                                                                            '/ '
                                                                                                                                                                            'Alimeeting '
                                                                                                                                                                            '24.86、ともに最高。比較値：Gemini '
                                                                                                                                                                            '3 '
                                                                                                                                                                            'Pro '
                                                                                                                                                                            '22.75/26.75、Doubao '
                                                                                                                                                                            '18.18/25.25、ElevenLabs '
                                                                                                                                                                            '19.58/25.70、Gemini '
                                                                                                                                                                            '2.5 '
                                                                                                                                                                            'Pro '
                                                                                                                                                                            '42.70/27.43。'),
 '综合档位估算': ('Overall tier estimate', '総合的な水準推定'),
 'AISHELL-4 同表最佳，但属长音频多人口径，与朗读集不可直比': ('Best AISHELL-4 result; long-form multi-speaker tests cannot directly compare '
                                       'with read speech',
                                       'AISHELL-4で最高。ただし長時間・複数話者と朗読のデータは直接比較できません'),
 'MOSS 的公开成绩都在长音频/多说话人集（AISHELL-4/Alimeeting/Podcast/Movies），无普通话朗读集数字。其胜出对象含通用 API（Doubao/Gemini），中文能力属第一梯队；按档位估 80（区间 75-85）。说话人区分能力不计入文字准确度。': ('Published '
                                                                                                                                                   'MOSS '
                                                                                                                                                   'results '
                                                                                                                                                   'cover '
                                                                                                                                                   'long-form/multi-speaker '
                                                                                                                                                   'AISHELL-4, '
                                                                                                                                                   'Alimeeting, '
                                                                                                                                                   'Podcast '
                                                                                                                                                   'and '
                                                                                                                                                   'Movies, '
                                                                                                                                                   'with '
                                                                                                                                                   'no '
                                                                                                                                                   'Mandarin '
                                                                                                                                                   'read-speech '
                                                                                                                                                   'values. '
                                                                                                                                                   'It '
                                                                                                                                                   'beats '
                                                                                                                                                   'general '
                                                                                                                                                   'APIs '
                                                                                                                                                   'including '
                                                                                                                                                   'Doubao/Gemini; '
                                                                                                                                                   'estimated '
                                                                                                                                                   'top '
                                                                                                                                                   'Chinese '
                                                                                                                                                   'tier '
                                                                                                                                                   '80 '
                                                                                                                                                   '(75–85). '
                                                                                                                                                   'Diarization '
                                                                                                                                                   'is '
                                                                                                                                                   'excluded '
                                                                                                                                                   'from '
                                                                                                                                                   'text '
                                                                                                                                                   'accuracy.',
                                                                                                                                                   'MOSSの公開成績は長時間・複数話者のAISHELL-4、Alimeeting、Podcast、Moviesで、普通話朗読の値はありません。Doubao/Geminiなどの汎用APIを上回るため、中国語の上位水準80（75～85）と推定。話者分離はテキスト精度に含めません。'),
 '通用参考（方言未验证）': ('General reference; dialects unverified', '一般参考値、方言は未検証'),
 '中文长音频证据迁移；无方言集成绩': ('Based on Chinese long-form evidence; no dialect scores', '中国語長時間音声の根拠を転用、方言成績なし'),
 '官方表未含方言测试集；以中文整体表现给通用档位 70，方言单独未验证。': ('The official table has no dialect tests. General tier 70 is based on overall '
                                         'Chinese performance; dialects remain unverified.',
                                         '公式表に方言テストはありません。中国語全体の成績から一般水準70とし、方言は未検証です。'),
 '官方环境参考': ('Official environment reference', '公式環境の参考値'),
 'RTF 0.0197（单张 H100 · SGLang Omni · 长音频 · 并发 1）': ('RTF 0.0197 (one H100, SGLang Omni, long audio, concurrency 1)',
                                                    'RTF 0.0197（H100 1枚、SGLang Omni、長時間音声、並列数1）'),
 '官方 SGLang Omni 吞吐表：aishell4_long 并发 1 RTF 0.0197（≈RTFx 51，H100）。跨硬件按统一速度尺度折算约 35（区间 25-45）。不代表本机速度。': ('Official '
                                                                                                         'SGLang Omni: '
                                                                                                         'aishell4_long '
                                                                                                         'at '
                                                                                                         'concurrency '
                                                                                                         '1, RTF '
                                                                                                         '0.0197 '
                                                                                                         '(RTFx≈51 on '
                                                                                                         'H100). '
                                                                                                         'Cross-hardware '
                                                                                                         'calibration '
                                                                                                         'estimates 35 '
                                                                                                         '(25–45). '
                                                                                                         'This is not '
                                                                                                         'your '
                                                                                                         "computer's "
                                                                                                         'speed.',
                                                                                                         '公式SGLang '
                                                                                                         'Omni：aishell4_long、並列数1、RTF '
                                                                                                         '0.0197（H100でRTFx約51）。ハードウェアを跨ぐ較正で35（25～45）と推定。手元のPCの速度ではありません。'),
 '跨表校准（Qwen 官方表）': ('Cross-table calibration via Qwen', 'Qwen公式表を介した較正'),
 'WenetSpeech net 6.35%（Qwen 表复测）经 Qwen3-ASR 锚换算': ("WenetSpeech net 6.35% in Qwen's retest, calibrated through "
                                                    'Qwen3-ASR',
                                                    'Qwen再評価のWenetSpeech net 6.35%をQwen3-ASR基準で較正'),
 'Qwen 官方表同表：Fun-ASR-Nano WS net 6.35 vs Qwen3-ASR-1.7B 4.97；Qwen 中文锚分 88（FireRed 表）→ 88×sqrt(4.97/6.35)=78。Fun 自报同集 6.01（另一管线），Fleurs-zh 自报 2.56 vs Qwen 表 3.51，两套来源分行保留。官方卡 TODO：2512 版无时间戳/说话人。': ("Qwen's "
                                                                                                                                                                                                      'table: '
                                                                                                                                                                                                      'Fun-ASR-Nano '
                                                                                                                                                                                                      'WS '
                                                                                                                                                                                                      'net '
                                                                                                                                                                                                      '6.35 '
                                                                                                                                                                                                      'vs '
                                                                                                                                                                                                      'Qwen3-ASR-1.7B '
                                                                                                                                                                                                      '4.97. '
                                                                                                                                                                                                      'Qwen '
                                                                                                                                                                                                      'anchor '
                                                                                                                                                                                                      '88 '
                                                                                                                                                                                                      'from '
                                                                                                                                                                                                      'FireRed '
                                                                                                                                                                                                      'yields '
                                                                                                                                                                                                      '88×sqrt(4.97/6.35)=78. '
                                                                                                                                                                                                      'Fun '
                                                                                                                                                                                                      'self-reports '
                                                                                                                                                                                                      '6.01; '
                                                                                                                                                                                                      'Fleurs-zh '
                                                                                                                                                                                                      'self-report '
                                                                                                                                                                                                      'is '
                                                                                                                                                                                                      '2.56 '
                                                                                                                                                                                                      'vs '
                                                                                                                                                                                                      'Qwen '
                                                                                                                                                                                                      'retest '
                                                                                                                                                                                                      '3.51. '
                                                                                                                                                                                                      'Keep '
                                                                                                                                                                                                      'sources '
                                                                                                                                                                                                      'separate. '
                                                                                                                                                                                                      'Official '
                                                                                                                                                                                                      'TODO: '
                                                                                                                                                                                                      'version '
                                                                                                                                                                                                      '2512 '
                                                                                                                                                                                                      'lacks '
                                                                                                                                                                                                      'timestamps/diarization.',
                                                                                                                                                                                                      'Qwen表：Fun-ASR-Nano '
                                                                                                                                                                                                      'WS '
                                                                                                                                                                                                      'net '
                                                                                                                                                                                                      '6.35、Qwen3-ASR-1.7B '
                                                                                                                                                                                                      '4.97。FireRed由来のQwen基準88から88×sqrt(4.97/6.35)=78。Fun自己申告6.01、Fleurs-zhは自己申告2.56とQwen再評価3.51を別々に保持。公式TODOでは2512版に時刻・話者分離は未対応です。'),
 '官方卡行业集+方言覆盖': ('Official domain tests and dialect coverage', '公式の業務データ評価と方言対応'),
 '官方 7 方言覆盖；行业方言集 28.18%（vs 闭源 7.7B 15.21）': ('Seven official dialect groups; domain dialect CER 28.18% vs closed 7.7B '
                                              'at 15.21',
                                              '公式7方言、業務方言CER 28.18%（非公開7.7Bは15.21）'),
 'Fun-ASR-Nano 官方卡：吴粤闽客赣湘晋 7 方言+26 口音；行业 Dialect 集 28.18%。档位估 75。': ('Fun-ASR-Nano lists Wu, Yue, Min, Hakka, Gan, '
                                                                     'Xiang and Jin plus 26 accents; domain Dialect '
                                                                     'score 28.18%. Estimated tier 75.',
                                                                     'Fun-ASR-Nanoは呉・粤・閩・客家・贛・湘・晋と26アクセントに対応。業務Dialect成績28.18%から水準75と推定。'),
 '官方卡英语集': ('Official English datasets', '公式英語データセット'),
 'LibriSpeech clean 1.76% / other 4.33%（自报）': ('LibriSpeech clean 1.76% / other 4.33%, self-reported',
                                               'LibriSpeech clean 1.76% / other 4.33%（自己申告）'),
 '官方卡英语自报成绩良好但未入 AA 榜；按档位估 70。': ('Good self-reported English scores but absent from AA; estimated tier 70.',
                                  '公式の英語自己申告値は良好ですがAAには未掲載。水準70と推定。'),
 '档位估算': ('Tier estimate', '水準推定'),
 '0.8B 端到端；官方称低延迟实时转写，无公开 RTF': ('0.8B end-to-end; claimed low-latency real-time ASR without published RTF',
                                 '0.8Bエンドツーエンド、低遅延リアルタイムと記載、RTF未公開'),
 '官方卡无 RTF 数值，标注 low-latency real-time；按 0.8B 端到端 LLM-ASR 档位估 35（区间 25-45）。': ('No RTF on the model card, only a '
                                                                               'low-latency real-time claim. Estimated '
                                                                               '0.8B LLM-ASR tier 35 (25–45).',
                                                                               'モデルカードにRTFはなく、低遅延リアルタイムとの記載のみ。0.8B '
                                                                               'LLM-ASRの水準35（25～45）と推定。'),
 '技术报告同表对照': ('Same-table technical report comparison', '技術報告の同一表比較'),
 'AISHELL-1 2.96% / WS 7.44·7.84%，同表全面优于 Whisper-Large-v3': ('AISHELL-1 2.96%, WS 7.44/7.84%; beats Whisper-Large-v3 '
                                                             'throughout the table',
                                                             'AISHELL-1 2.96%、WS 7.44/7.84%。同一表でWhisper-Large-v3を上回る'),
 'SenseVoice 技术报告 Table 6：AISHELL-1 2.96 vs Whisper-L-v3 5.14；WS meeting 7.44 vs 18.87；WS net 7.84 vs 10.48。经 whisper-v3 锚（约 60）换算区间 63-95，测试集难度差异大，取档位 75（区间 70-83）。': ('SenseVoice '
                                                                                                                                                                         'Table '
                                                                                                                                                                         '6: '
                                                                                                                                                                         'AISHELL-1 '
                                                                                                                                                                         '2.96 '
                                                                                                                                                                         'vs '
                                                                                                                                                                         'Whisper-L-v3 '
                                                                                                                                                                         '5.14; '
                                                                                                                                                                         'WS '
                                                                                                                                                                         'meeting '
                                                                                                                                                                         '7.44 '
                                                                                                                                                                         'vs '
                                                                                                                                                                         '18.87; '
                                                                                                                                                                         'WS '
                                                                                                                                                                         'net '
                                                                                                                                                                         '7.84 '
                                                                                                                                                                         'vs '
                                                                                                                                                                         '10.48. '
                                                                                                                                                                         'Calibration '
                                                                                                                                                                         'via '
                                                                                                                                                                         'whisper-v3 '
                                                                                                                                                                         '(about '
                                                                                                                                                                         '60) '
                                                                                                                                                                         'spans '
                                                                                                                                                                         '63–95. '
                                                                                                                                                                         'Due '
                                                                                                                                                                         'to '
                                                                                                                                                                         'test '
                                                                                                                                                                         'difficulty '
                                                                                                                                                                         'differences, '
                                                                                                                                                                         'use '
                                                                                                                                                                         '75 '
                                                                                                                                                                         '(70–83).',
                                                                                                                                                                         'SenseVoice '
                                                                                                                                                                         'Table '
                                                                                                                                                                         '6：AISHELL-1 '
                                                                                                                                                                         '2.96対5.14、WS '
                                                                                                                                                                         'meeting '
                                                                                                                                                                         '7.44対18.87、WS '
                                                                                                                                                                         'net '
                                                                                                                                                                         '7.84対10.48（比較はWhisper-L-v3）。whisper-v3基準約60で較正すると63～95。難易度差を考慮し75（70～83）を採用。'),
 '粤语专项优化': ('Optimized for Cantonese', '広東語向け最適化'),
 '官方主打中文/粤语；无方言集数值': ('Official focus on Chinese/Cantonese; no dialect benchmark values', '公式は中国語・広東語を重視、方言評価値なし'),
 'checkpoint 语言集含粤语且官方称中文粤语有优势；未核到方言测试集数字，档位估 60。': ('Cantonese is included and the project claims strengths in '
                                                     'Chinese/Cantonese. No verified dialect test values; estimated '
                                                     'tier 60.',
                                                     '広東語に対応し、公式は中国語・広東語に強みがあると記載。検証済み方言評価値はなく、水準60と推定。'),
 '英语公开证据有限（论文 LS clean 3.15%）': ('Limited English evidence (paper: LS clean 3.15%)', '英語の根拠は限定的（論文LS clean 3.15%）'),
 '官方速度图示+论文延迟': ('Official speed chart and paper latency', '公式速度図と論文の遅延'),
 '官方称 >15x Whisper-Large；论文 10s 音频 70ms（RTF≈0.007）': ('Claimed >15× Whisper-Large; paper reports 70 ms for 10 s audio, '
                                                      'RTF≈0.007',
                                                      '公式はWhisper-Largeの15倍超、論文は10秒音声70 ms、RTF約0.007'),
 'README 图示（硬件见图注）：>5x Whisper-Small、>15x Whisper-Large；论文 Table 7 十秒音频 70ms。折算 RTFx 约 50-180（跨环境），档位估 60（区间 55-70）。CPU 可用。': ('README '
                                                                                                                               'chart '
                                                                                                                               'claims '
                                                                                                                               '>5× '
                                                                                                                               'Whisper-Small '
                                                                                                                               'and '
                                                                                                                               '>15× '
                                                                                                                               'Whisper-Large; '
                                                                                                                               'hardware '
                                                                                                                               'is '
                                                                                                                               'in '
                                                                                                                               'the '
                                                                                                                               'caption. '
                                                                                                                               'Paper '
                                                                                                                               'Table '
                                                                                                                               '7 '
                                                                                                                               'gives '
                                                                                                                               '70 '
                                                                                                                               'ms '
                                                                                                                               'for '
                                                                                                                               '10 '
                                                                                                                               's '
                                                                                                                               'audio. '
                                                                                                                               'Cross-environment '
                                                                                                                               'RTFx '
                                                                                                                               'estimate '
                                                                                                                               '50–180; '
                                                                                                                               'tier '
                                                                                                                               '60 '
                                                                                                                               '(55–70). '
                                                                                                                               'CPU '
                                                                                                                               'supported.',
                                                                                                                               'README図はWhisper-Smallの5倍超、Whisper-Largeの15倍超（ハードウェアは図注）。論文Table '
                                                                                                                               '7は10秒音声70 '
                                                                                                                               'ms。環境を跨ぐRTFx推定50～180から水準60（55～70）。CPU対応。'),
 '官方卡跨集区间': ('Official cross-dataset range', '公式データセット間の範囲'),
 'AISHELL-1 1.95% / WS meeting 6.97%，跨集表现差异大': ('AISHELL-1 1.95% / WS meeting 6.97%; performance varies across sets',
                                                'AISHELL-1 1.95% / WS meeting 6.97%、データ間の差が大きい'),
 '官方卡：AISHELL-1 1.95（w/o LM；w/ LM 1.68）、WS meeting 6.97、net 6.74。对照 FireRed 同集 0.57/4.53 换算区间约 52-78，取中低档 70（区间 65-75）。2018-2022 代模型，新模型已普遍超越。': ('Official '
                                                                                                                                                  'card: '
                                                                                                                                                  'AISHELL-1 '
                                                                                                                                                  '1.95 '
                                                                                                                                                  'without '
                                                                                                                                                  'LM, '
                                                                                                                                                  '1.68 '
                                                                                                                                                  'with '
                                                                                                                                                  'LM; '
                                                                                                                                                  'WS '
                                                                                                                                                  'meeting '
                                                                                                                                                  '6.97, '
                                                                                                                                                  'net '
                                                                                                                                                  '6.74. '
                                                                                                                                                  'Comparing '
                                                                                                                                                  "FireRed's "
                                                                                                                                                  '0.57/4.53 '
                                                                                                                                                  'implies '
                                                                                                                                                  '52–78; '
                                                                                                                                                  'conservative '
                                                                                                                                                  'tier '
                                                                                                                                                  '70 '
                                                                                                                                                  '(65–75). '
                                                                                                                                                  'A '
                                                                                                                                                  '2018–2022 '
                                                                                                                                                  'generation '
                                                                                                                                                  'model, '
                                                                                                                                                  'generally '
                                                                                                                                                  'surpassed '
                                                                                                                                                  'by '
                                                                                                                                                  'newer '
                                                                                                                                                  'models.',
                                                                                                                                                  '公式カード：AISHELL-1はLMなし1.95、あり1.68、WS '
                                                                                                                                                  'meeting '
                                                                                                                                                  '6.97、net '
                                                                                                                                                  '6.74。FireRedの0.57/4.53との比較から52～78、控えめに70（65～75）。2018～2022世代で、新しいモデルが概ね上回っています。'),
 '官方卡未列方言': ('No dialects listed on the official card', '公式カードに方言の記載なし'),
 '模型卡无方言集数值': ('No dialect test values on the model card', 'モデルカードに方言評価値なし'),
 '官方卡未提供方言覆盖证据；档位估 55。': ('No official dialect coverage evidence; estimated tier 55.', '公式の方言対応根拠がなく、水準55と推定。'),
 '英语不支持（中文专用模型）': ('English unsupported: Chinese-only model', '中国語専用で英語は非対応'),
 '官方 RTF+120x 声明': ('Official RTF and 120× real-time claim', '公式RTFとリアルタイム120倍の記載'),
 'RTF 0.0251（V100·batch1）；HF 卡称 GPU 120x 实时': ('RTF 0.0251 (V100, batch 1); HF card claims GPU 120× real time',
                                               'RTF 0.0251（V100、batch 1）、HFカードはGPUでリアルタイム120倍と記載'),
 '官方卡 indexing：V100 batch1 RTF 0.0251（≈RTFx 40，旧卡）；HF 卡称非自回归 GPU 120x 实时（≈RTFx 120）。跨代硬件折算档位 50（区间 35-55）。': ('Official '
                                                                                                              'indexing: '
                                                                                                              'V100 '
                                                                                                              'batch 1 '
                                                                                                              'RTF '
                                                                                                              '0.0251 '
                                                                                                              '(RTFx≈40, '
                                                                                                              'older '
                                                                                                              'GPU). '
                                                                                                              'HF card '
                                                                                                              'claims '
                                                                                                              'non-autoregressive '
                                                                                                              'GPU '
                                                                                                              '120× '
                                                                                                              'real '
                                                                                                              'time '
                                                                                                              '(RTFx≈120). '
                                                                                                              'Cross-generation '
                                                                                                              'hardware '
                                                                                                              'tier 50 '
                                                                                                              '(35–55).',
                                                                                                              '公式indexingはV100 '
                                                                                                              'batch '
                                                                                                              '1でRTF '
                                                                                                              '0.0251（RTFx約40、旧世代GPU）。HFカードは非自己回帰GPUでリアルタイム120倍（RTFx約120）。世代間換算の水準50（35～55）。'),
 'AA 实测 Groq turbo WER 4.6%；OpenASR 7.83% 同模型': ('AA measures Groq turbo WER 4.6%; same model scores 7.83% on OpenASR',
                                                 'AAのGroq turbo WER 4.6%、同一モデルのOpenASRは7.83%'),
 '统一 AA 尺度：榜内最佳 MAI-Transcribe-2 2.0% → turbo 4.6% = 66。OpenASR 尺度下 turbo 为 85（该组最佳 canary 5.63）——两榜测试集不同，卡片用 AA 统一尺度，技术说明保留两组原始数字。': ('Unified '
                                                                                                                                       'AA '
                                                                                                                                       'scale: '
                                                                                                                                       'best '
                                                                                                                                       'MAI-Transcribe-2 '
                                                                                                                                       '2.0% '
                                                                                                                                       'versus '
                                                                                                                                       'turbo '
                                                                                                                                       '4.6% '
                                                                                                                                       'gives '
                                                                                                                                       '66. '
                                                                                                                                       'On '
                                                                                                                                       'OpenASR '
                                                                                                                                       'turbo '
                                                                                                                                       'scores '
                                                                                                                                       '85, '
                                                                                                                                       'where '
                                                                                                                                       'canary '
                                                                                                                                       'is '
                                                                                                                                       'best '
                                                                                                                                       'at '
                                                                                                                                       '5.63. '
                                                                                                                                       'Different '
                                                                                                                                       'test '
                                                                                                                                       'sets: '
                                                                                                                                       'cards '
                                                                                                                                       'use '
                                                                                                                                       'AA '
                                                                                                                                       'while '
                                                                                                                                       'technical '
                                                                                                                                       'details '
                                                                                                                                       'retain '
                                                                                                                                       'both '
                                                                                                                                       'raw '
                                                                                                                                       'results.',
                                                                                                                                       'AA統一基準では最高のMAI-Transcribe-2 '
                                                                                                                                       '2.0%対turbo '
                                                                                                                                       '4.6%で66。OpenASRではcanary '
                                                                                                                                       '5.63が最高でturboは85。データセットが異なるため、カードはAA基準、詳細には両方の原値を保持します。'),
 'large-v3 同表外推': ('Extrapolation from large-v3', 'large-v3からの推定'),
 '无 turbo 专属中文数据；large-v3 经 Qwen 表换算约 62，turbo 略降': ('No turbo-specific Chinese data; large-v3 calibrates to about 62 '
                                                     'via Qwen, with a small reduction for turbo',
                                                     'turbo専用の中国語データなし。Qwen経由でlarge-v3約62、turboは小幅減'),
 'Qwen 官方表（large-v3，非本工程 turbo）：WS net 9.86 / meeting 19.11 / Fleurs-zh 4.09 / KeSpeech 28.79。经 Qwen 锚换算中文约 62；turbo 为 v3 剪枝微调（官方称轻微退化）→ 档位 60。中文是 Whisper 相对弱项。': ('Qwen '
                                                                                                                                                                    'table '
                                                                                                                                                                    'for '
                                                                                                                                                                    'large-v3, '
                                                                                                                                                                    'not '
                                                                                                                                                                    'turbo: '
                                                                                                                                                                    'WS '
                                                                                                                                                                    'net '
                                                                                                                                                                    '9.86, '
                                                                                                                                                                    'meeting '
                                                                                                                                                                    '19.11, '
                                                                                                                                                                    'Fleurs-zh '
                                                                                                                                                                    '4.09, '
                                                                                                                                                                    'KeSpeech '
                                                                                                                                                                    '28.79. '
                                                                                                                                                                    'Qwen '
                                                                                                                                                                    'calibration '
                                                                                                                                                                    'gives '
                                                                                                                                                                    'about '
                                                                                                                                                                    '62. '
                                                                                                                                                                    'Turbo '
                                                                                                                                                                    'is '
                                                                                                                                                                    'pruned/fine-tuned '
                                                                                                                                                                    'v3 '
                                                                                                                                                                    'with '
                                                                                                                                                                    'claimed '
                                                                                                                                                                    'slight '
                                                                                                                                                                    'degradation, '
                                                                                                                                                                    'so '
                                                                                                                                                                    'tier '
                                                                                                                                                                    '60. '
                                                                                                                                                                    'Chinese '
                                                                                                                                                                    'is '
                                                                                                                                                                    'a '
                                                                                                                                                                    'relative '
                                                                                                                                                                    'weakness.',
                                                                                                                                                                    'Qwen表のlarge-v3（turboではありません）：WS '
                                                                                                                                                                    'net '
                                                                                                                                                                    '9.86、meeting '
                                                                                                                                                                    '19.11、Fleurs-zh '
                                                                                                                                                                    '4.09、KeSpeech '
                                                                                                                                                                    '28.79。Qwen基準で約62。turboはv3の枝刈り・微調整版で公式に軽微な低下とあるため水準60。中国語は比較的弱い領域です。'),
 'large-v3 KeSpeech 外推': ('Extrapolation from large-v3 KeSpeech', 'large-v3のKeSpeechから推定'),
 'large-v3 KeSpeech 28.79%（Qwen 表）——方言显著偏弱': ("large-v3 KeSpeech 28.79% in Qwen's table; weak dialect performance",
                                              'Qwen表のlarge-v3 KeSpeech 28.79%、方言は弱め'),
 'KeSpeech（方言）large-v3 28.79 vs Qwen3 5.10；经锚换算约 40，turbo 再降 → 档位 35。': ('KeSpeech: large-v3 28.79 vs Qwen3 5.10. '
                                                                         'Calibrates to about 40, reduced for turbo to '
                                                                         'tier 35.',
                                                                         'KeSpeechはlarge-v3 28.79対Qwen3 '
                                                                         '5.10。基準換算約40からturbo分を減らして水準35。'),
 'RTFx 200.19（OpenASR 榜单统一环境）': ('RTFx 200.19 in the unified OpenASR environment', 'OpenASR統一環境でRTFx 200.19'),
 '官方 HF 卡所载 OpenASR：RTFx 200.19（≈RTF 0.005，榜单统一环境）。统一尺度：canary 418=100 → turbo 69。不代表本机速度；torch.compile 另有 4.5x 官方声明。': ('Official '
                                                                                                                         'HF '
                                                                                                                         "card's "
                                                                                                                         'OpenASR '
                                                                                                                         'RTFx '
                                                                                                                         '200.19 '
                                                                                                                         '(RTF≈0.005). '
                                                                                                                         'Unified '
                                                                                                                         'scale: '
                                                                                                                         'canary '
                                                                                                                         '418=100, '
                                                                                                                         'turbo=69. '
                                                                                                                         'Not '
                                                                                                                         'local '
                                                                                                                         'speed. '
                                                                                                                         'A '
                                                                                                                         'separate '
                                                                                                                         'official '
                                                                                                                         'torch.compile '
                                                                                                                         'claim '
                                                                                                                         'reports '
                                                                                                                         '4.5×.',
                                                                                                                         '公式HFカードのOpenASRはRTFx '
                                                                                                                         '200.19（RTF約0.005）。canary '
                                                                                                                         '418=100を基準にturboは69。ローカル速度ではありません。別途torch.compileで4.5倍との公式記載があります。'),
 '跨榜校准（OpenASR→AA）': ('Cross-leaderboard calibration: OpenASR → AA', 'ランキング間較正：OpenASR → AA'),
 'OpenASR Mean WER 7.03%；经 turbo 锚换算 AA 尺度': ('OpenASR mean WER 7.03%, calibrated to AA via turbo',
                                              'OpenASR平均WER 7.03%をturbo経由でAAへ較正'),
 'OpenASR 7.03 → AA 等效 7.03/1.70=4.13% → sqrt(2.0/4.13)×100≈70。': ('OpenASR 7.03 → AA-equivalent 7.03/1.70=4.13%; '
                                                                   'sqrt(2.0/4.13)×100≈70.',
                                                                   'OpenASR '
                                                                   '7.03→AA換算7.03/1.70=4.13%、sqrt(2.0/4.13)×100≈70。'),
 '通用参考·中文证据有限': ('General reference; limited Chinese evidence', '一般参考値、中国語の根拠は限定的'),
 '官方称同类开源均错最低 4.10；中文成绩图为图片无文本数值': ('Official claim: lowest open-model average error 4.10; Chinese chart has no text '
                                    'values',
                                    '公式は同種公開モデル最低の平均誤差4.10と記載。中国語図にテキスト値なし'),
 '官方模型卡 benchmark 图无文本数字（无法转录），正文称 avg error 4.10 最低；Qwen 多语表 GLM 落后 whisper-v3 约 1.5 倍错误率。中文证据有限，档位估 75。': ('Official '
                                                                                                             'benchmark '
                                                                                                             'chart '
                                                                                                             'has no '
                                                                                                             'transcribable '
                                                                                                             'text '
                                                                                                             'values; '
                                                                                                             'body '
                                                                                                             'claims '
                                                                                                             'lowest '
                                                                                                             'average '
                                                                                                             'error '
                                                                                                             '4.10. In '
                                                                                                             "Qwen's "
                                                                                                             'multilingual '
                                                                                                             'table '
                                                                                                             'GLM has '
                                                                                                             'about '
                                                                                                             '1.5× '
                                                                                                             "whisper-v3's "
                                                                                                             'error. '
                                                                                                             'Limited '
                                                                                                             'Chinese '
                                                                                                             'evidence; '
                                                                                                             'tier 75.',
                                                                                                             '公式評価図は文字として抽出可能な数値がなく、本文は最低平均誤差4.10と記載。Qwen多言語表ではGLMの誤り率がwhisper-v3の約1.5倍。中国語の根拠は限定的で、水準75と推定。'),
 '官方主打粤语/方言': ('Official Cantonese/dialect focus', '公式は広東語・方言を重視'),
 '官方模型卡主打粤语与方言优化': ('Official card emphasizes Cantonese and dialect optimization', '公式カードは広東語・方言への最適化を強調'),
 '官方称对粤语、方言、低音量语音优化；无逐集数值，档位估 75。': ('Officially optimized for Cantonese, dialects and quiet speech, without per-set '
                                     'values; tier 75.',
                                     '広東語、方言、小音量向けの最適化を公式記載。セット別数値はなく、水準75。'),
 'RTFx 145.28（官方卡自报同榜结果）': ('RTFx 145.28, self-reported official leaderboard result',
                            'RTFx 145.28、公式カード掲載の同ランキング自己申告値'),
 'OpenASR 榜单口径 RTFx 145.28（≈RTF 0.0069）。统一尺度 canary 418=100 → 59。': ('OpenASR RTFx 145.28 (RTF≈0.0069). With canary '
                                                                     '418=100, unified score is 59.',
                                                                     'OpenASR RTFx 145.28（RTF約0.0069）。canary '
                                                                     '418=100の統一基準で59。'),
 'OpenASR Mean WER 5.63%；经 turbo 锚换算 AA 尺度': ('OpenASR mean WER 5.63%, calibrated to AA via turbo',
                                              'OpenASR平均WER 5.63%をturbo経由でAAへ較正'),
 'OpenASR 5.63 → AA 等效 5.63/1.70=3.31% → sqrt(2.0/3.31)×100≈78。OpenASR 组内它仍是最佳（严格分 100，见技术说明）。': ('OpenASR 5.63 → '
                                                                                                  'AA-equivalent '
                                                                                                  '5.63/1.70=3.31%; '
                                                                                                  'sqrt(2.0/3.31)×100≈78. '
                                                                                                  'It remains best '
                                                                                                  'within OpenASR, '
                                                                                                  'with strict group '
                                                                                                  'score 100; see '
                                                                                                  'details.',
                                                                                                  'OpenASR '
                                                                                                  '5.63→AA換算5.63/1.70=3.31%、sqrt(2.0/3.31)×100≈78。OpenASRグループ内では依然最高で、厳密な同条件スコアは100です。詳細を参照。'),
 '官方明确仅可靠支持 English（英语专用模型）': ('Officially reliable for English only (English-specific model)',
                               '公式に信頼できる対応は英語のみ（英語専用モデル）'),
 '官方明确仅可靠支持 English': ('Officially reliable for English only', '公式に信頼できる対応は英語のみ'),
 'RTFx 418（OpenASR 榜单，全目录最快）': ('RTFx 418 on OpenASR, fastest in this catalog', 'OpenASR RTFx 418、このカタログで最速'),
 'OpenASR RTFx 418（≈RTF 0.0024，榜单统一环境）——本参考目录内公开速度最佳，定标 100。': ('OpenASR RTFx 418 (RTF≈0.0024, unified environment) is '
                                                                'the fastest published result in this reference '
                                                                'catalog, setting the scale to 100.',
                                                                'OpenASR RTFx '
                                                                '418（RTF約0.0024、統一環境）はこの参考カタログの公開最速値で、基準100とします。'),
 '官方卡脚注：RTF 0.092（~1x 实时）。统一尺度 sqrt(10.9/418)≈16 → 15。同家族 CTC 版本（300M-7B）RTF 0.001-0.006 远快于 LLM 版。': ('Official card '
                                                                                                       'footnote: RTF '
                                                                                                       '0.092, about '
                                                                                                       'real time. '
                                                                                                       'Unified '
                                                                                                       'sqrt(10.9/418)≈16, '
                                                                                                       'rounded to 15. '
                                                                                                       'Same-family '
                                                                                                       'CTC models '
                                                                                                       '(300M–7B) have '
                                                                                                       'much faster '
                                                                                                       'RTF '
                                                                                                       '0.001–0.006.',
                                                                                                       '公式カード脚注はRTF '
                                                                                                       '0.092（約リアルタイム）。統一基準sqrt(10.9/418)≈16から15。同系CTC版（300M～7B）はRTF '
                                                                                                       '0.001～0.006でLLM版より大幅に高速です。'),
 'Qwen 官方同表': ('Qwen official comparison table', 'Qwen公式比較表'),
 'AAS 中文 33.1ms，同表最佳（NFA 109.8 / MFA 161.1）': ('Chinese AAS 33.1 ms, best in table (NFA 109.8 / MFA 161.1)',
                                               '中国語AAS 33.1 ms、同一表で最高（NFA 109.8 / MFA 161.1）'),
 'Qwen3-ForcedAligner 官方对齐评测：中文 Raw AAS 33.1ms。AAS 只衡量给定文本对齐，不代表从零转写准确率。': ('Qwen3-ForcedAligner official Chinese Raw '
                                                                            'AAS: 33.1 ms. AAS measures alignment of '
                                                                            'given text, not transcription from '
                                                                            'scratch.',
                                                                            'Qwen3-ForcedAligner公式の中国語Raw AASは33.1 '
                                                                            'ms。AASは指定テキストの整列を評価し、新規文字起こしの精度ではありません。'),
 '非从零转写模型：准确度不适用（对齐模型）': ('Not an ASR model: transcription accuracy is not applicable to alignment',
                          '新規文字起こしモデルではないため、文字起こし精度は適用外'),
 '同系换算估算': ('Same-family estimate', '同系列モデルからの推定'),
 '托管 qwen3-asr-flash；本地 1.7B 官方中文 88，托管版未单独公布': ('Hosted qwen3-asr-flash; local 1.7B Chinese score 88, no separate '
                                                 'hosted score',
                                                 'ホスト型qwen3-asr-flash。ローカル1.7Bの中国語は88、ホスト版の個別成績なし'),
 'DashScope qwen3-asr-flash 与开源 Qwen3-ASR 同系；官方未公布托管版逐集成绩。按 1.7B 官方中文 88 取同系档位 85（托管版可能有差异）。官方称支持传统七大方言+20+口音官话（2026-06 更新版描述）。': ('DashScope '
                                                                                                                                   'qwen3-asr-flash '
                                                                                                                                   'shares '
                                                                                                                                   'the '
                                                                                                                                   'open '
                                                                                                                                   'Qwen3-ASR '
                                                                                                                                   'family '
                                                                                                                                   'but '
                                                                                                                                   'has '
                                                                                                                                   'no '
                                                                                                                                   'per-set '
                                                                                                                                   'hosted '
                                                                                                                                   'scores. '
                                                                                                                                   'Estimated '
                                                                                                                                   'tier '
                                                                                                                                   '85 '
                                                                                                                                   'from '
                                                                                                                                   'local '
                                                                                                                                   '1.7B '
                                                                                                                                   'score '
                                                                                                                                   '88; '
                                                                                                                                   'hosted '
                                                                                                                                   'behavior '
                                                                                                                                   'may '
                                                                                                                                   'differ. '
                                                                                                                                   'Official '
                                                                                                                                   'June '
                                                                                                                                   '2026 '
                                                                                                                                   'description '
                                                                                                                                   'lists '
                                                                                                                                   'seven '
                                                                                                                                   'Chinese '
                                                                                                                                   'dialect '
                                                                                                                                   'groups '
                                                                                                                                   'and '
                                                                                                                                   '20+ '
                                                                                                                                   'Mandarin '
                                                                                                                                   'accents.',
                                                                                                                                   'DashScope '
                                                                                                                                   'qwen3-asr-flashは公開Qwen3-ASRと同系で、ホスト版のセット別成績はありません。ローカル1.7Bの88から水準85と推定（ホスト版は差がある可能性）。2026年6月版の公式説明は七大方言と20以上の普通話アクセントに対応と記載。'),
 '官方方言声明': ('Official dialect statement', '公式の方言対応記載'),
 '官方称全面支持七大方言体系；无逐集数值': ('Officially supports seven dialect groups, with no per-set values', '公式は七大方言対応を記載、セット別数値なし'),
 '官方文档称 Qwen3/Qwen-Audio 3.0 ASR 支持汉语传统七大方言；无公开方言测试集数字，档位估 80。': ('Qwen3/Qwen-Audio 3.0 ASR documentation lists seven '
                                                                  'Chinese dialect groups without public test values; '
                                                                  'estimated tier 80.',
                                                                  'Qwen3/Qwen-Audio 3.0 '
                                                                  'ASR資料は中国語七大方言対応を記載。公開テスト値はなく、水準80と推定。'),
 '本地 1.7B 官方 Fleurs-en 3.35%；托管版未公布': ('Local 1.7B official Fleurs-en 3.35%; hosted result unpublished',
                                       'ローカル1.7Bの公式Fleurs-en 3.35%、ホスト版は未公開'),
 '同系 1.7B 官方英语集表现良好（LibriSpeech 1.63/3.38、Fleurs-en 3.35）；托管 flash 未单独公布，档位估 75。': ('Same-family 1.7B English results '
                                                                                    'are good: LibriSpeech 1.63/3.38, '
                                                                                    'Fleurs-en 3.35. No separate '
                                                                                    'hosted flash results; tier 75.',
                                                                                    '同系1.7Bの英語成績は良好（LibriSpeech '
                                                                                    '1.63/3.38、Fleurs-en '
                                                                                    '3.35）。ホスト型flashの個別値はなく、水準75。'),
 '服务档位估算': ('Service tier estimate', 'サービス水準の推定'),
 '云端托管 ASR 中档；未核到官方公开吞吐': ('Mid-tier hosted ASR; no verified official throughput', 'ホスト型ASRの中水準、公式スループット未確認'),
 'DashScope 未公布该模型公开 RTF/吞吐。同步接口单请求 ≤5 分钟内返回（含上传与推理），按云端托管离线转写档位估 40（区间 30-60）。本机/当前路由未实测。': ('DashScope publishes no '
                                                                                              'RTF/throughput for this '
                                                                                              'model. Synchronous '
                                                                                              'requests return within '
                                                                                              '5 minutes including '
                                                                                              'upload/inference. '
                                                                                              'Estimated cloud offline '
                                                                                              'tier 40 (30–60); '
                                                                                              'local/current route '
                                                                                              'untested.',
                                                                                              'DashScopeはこのモデルのRTF・スループットを未公開。同期リクエストはアップロードと推論を含め5分以内に応答。クラウドオフラインの水準40（30～60）と推定。ローカル・現在の経路は未測定です。'),
 'qwen-audio-3.0-asr-flash（qwen3-asr-flash 同代新命名）；托管版未单独公布': ('qwen-audio-3.0-asr-flash is a new same-generation name '
                                                              'for qwen3-asr-flash; no separate hosted scores',
                                                              'qwen-audio-3.0-asr-flashはqwen3-asr-flashと同世代の新名称。ホスト版個別成績なし'),
 'qwen-audio-3.0-asr-flash 为 Qwen3-ASR 家族托管版命名（同代）。按本地 1.7B 官方中文 88 取 85 档。与 qwen_api 卡的差异是接口/入口而非已证实的模型差异。': ('qwen-audio-3.0-asr-flash '
                                                                                                               'names '
                                                                                                               'a '
                                                                                                               'hosted '
                                                                                                               'model '
                                                                                                               'in the '
                                                                                                               'same '
                                                                                                               'Qwen3-ASR '
                                                                                                               'generation. '
                                                                                                               'Estimated '
                                                                                                               'Chinese '
                                                                                                               'tier '
                                                                                                               '85 '
                                                                                                               'from '
                                                                                                               'local '
                                                                                                               '1.7B '
                                                                                                               'score '
                                                                                                               '88. '
                                                                                                               'The '
                                                                                                               'difference '
                                                                                                               'from '
                                                                                                               'qwen_api '
                                                                                                               'is the '
                                                                                                               'interface, '
                                                                                                               'not a '
                                                                                                               'verified '
                                                                                                               'model '
                                                                                                               'difference.',
                                                                                                               'qwen-audio-3.0-asr-flashは同世代Qwen3-ASRのホスト版名称。ローカル1.7Bの中国語88から水準85。qwen_apiとの違いは接続入口であり、モデルの差は確認されていません。'),
 '官方称七大方言体系支持；无逐集数值': ('Official seven-dialect support; no per-set values', '公式は七大方言対応、セット別数値なし'),
 '同 qwen3-asr-flash 方言声明：官方支持汉语传统七大方言，无逐集数值。': ('Same dialect statement as qwen3-asr-flash: seven Chinese dialect '
                                                'groups, no per-set values.',
                                                'qwen3-asr-flashと同じ方言対応記載。中国語七大方言に対応し、セット別数値はありません。'),
 '同系 1.7B 官方英语集良好；托管版未公布': ('Good same-family 1.7B English results; hosted values unpublished',
                            '同系1.7Bの英語成績は良好、ホスト版は未公開'),
 '同 qwen3-asr-flash 英语依据（1.7B 官方英语集），档位估 75。': ('Same English evidence as qwen3-asr-flash from official 1.7B tests; '
                                                'tier 75.',
                                                'qwen3-asr-flashと同じ1.7B公式英語評価を根拠とし、水準75。'),
 '云端托管中档；未核到官方公开吞吐': ('Mid-tier cloud hosting; no verified official throughput', 'クラウドの中水準、公式スループット未確認'),
 '同 qwen3-asr-flash：无公开吞吐，档位 40（区间 30-60）。当前路由未实测。': ('Like qwen3-asr-flash, no published throughput; tier 40 (30–60). '
                                                      'Current route untested.',
                                                      'qwen3-asr-flashと同様、公開スループットなし。水準40（30～60）。現在の経路は未測定。'),
 '同模型不同接口': ('Same model, different interface', '同じモデルの別インターフェース'),
 'filetrans 为 qwen-audio-3.0-asr-flash 的异步录音文件接口': ('filetrans is the asynchronous recorded-file API for '
                                                    'qwen-audio-3.0-asr-flash',
                                                    'filetransはqwen-audio-3.0-asr-flashの非同期録音ファイルAPI'),
 'qwen-audio-3.0-asr-flash-filetrans 与同步 flash 同模型家族的文件转写接口（词级时间戳+speaker）；模型层同系 85，接口差异不改变识别质量。': ('qwen-audio-3.0-asr-flash-filetrans '
                                                                                                    'is the '
                                                                                                    'same-family file '
                                                                                                    'API with word '
                                                                                                    'timestamps and '
                                                                                                    'speakers. Model '
                                                                                                    'tier remains 85; '
                                                                                                    'the interface '
                                                                                                    'does not change '
                                                                                                    'recognition '
                                                                                                    'quality.',
                                                                                                    'qwen-audio-3.0-asr-flash-filetransは単語時刻・話者情報を提供する同系ファイルAPI。モデル水準は85で、入口の違い自体は認識品質を変えません。'),
 '异步端到端档位': ('Asynchronous end-to-end tier', '非同期処理全体の水準'),
 '吞吐型异步接口；端到端含排队与轮询': ('Throughput-oriented asynchronous API; total time includes queuing and polling',
                       'スループット重視の非同期API。待ち行列・ポーリングを含む'),
 'filetrans 为异步吞吐接口（单文件 ≤12h）；端到端耗时含上传/排队/轮询，短音频不占优。档位估 35（区间 25-55）。当前路由未实测。': ('filetrans accepts files up to 12 '
                                                                                 'hours. Total time includes upload, '
                                                                                 'queuing and polling, making it less '
                                                                                 'advantageous for short audio. Tier '
                                                                                 '35 (25–55); current route untested.',
                                                                                 'filetransは最大12時間のファイルに対応。アップロード・待ち行列・ポーリングを含むため短音声には不利です。水準35（25～55）、現在の経路は未測定。'),
 'AA 实测（Groq 路由）': ('AA measurement via Groq', 'Groq経由のAA実測'),
 'AA 实测 Groq Whisper large-v3-turbo WER 4.6%': ('AA measures Groq Whisper large-v3-turbo WER 4.6%',
                                                'AAのGroq Whisper large-v3-turbo実測WER 4.6%'),
 'AA 非流式榜单对 Groq 托管 turbo 的第一手实测：WER 4.6%（当前路由）。与本地 turbo 模型级一致（66）。': ('AA directly measures Groq-hosted turbo at WER '
                                                                        '4.6% on its non-streaming leaderboard. Same '
                                                                        'model-level reference as local turbo: 66.',
                                                                        'AA非ストリーミングランキングのGroq上turbo実測はWER '
                                                                        '4.6%。ローカルturboと同じモデル水準66です。'),
 'turbo 模型级参考': ('Turbo model-level reference', 'turboモデル水準の参考値'),
 '模型层=whisper-large-v3-turbo；中文无 turbo 专属数据': ('Whisper-large-v3-turbo model; no turbo-specific Chinese data',
                                               'Whisper-large-v3-turboモデル、中国語専用データなし'),
 '与本地 turbo 同 checkpoint，准确度随模型转移：中文档位 60（large-v3 外推 62×turbo 降幅）。托管预处理/解码设置差异未验证。': ('Same checkpoint as local '
                                                                                       'turbo: Chinese tier 60, '
                                                                                       'extrapolated from large-v3 at '
                                                                                       '62 with a turbo reduction. '
                                                                                       'Hosted preprocessing/decoding '
                                                                                       'differences are unverified.',
                                                                                       'ローカルturboと同じチェックポイントで、中国語水準60（large-v3の62からturbo分を減算）。ホスト側の前処理・デコード差は未検証です。'),
 'large-v3 KeSpeech 28.79% 外推；方言显著偏弱': ('Extrapolated from large-v3 KeSpeech 28.79%; weak dialect performance',
                                        'large-v3 KeSpeech 28.79%から推定、方言は弱め'),
 '同本地 turbo 方言依据。': ('Same dialect evidence as local turbo.', '方言の根拠はローカルturboと同じです。'),
 'AA 实测 Speed Factor 170.9（含网络）': ('AA measured Speed Factor 170.9, including network', 'AA実測Speed Factor 170.9、通信を含む'),
 'AA 对 Groq 路由实测 SF 170.9（音频时长/API 响应耗时，7 天中位）；经 turbo 锚（OpenASR RTFx 200.19）一致。当前路由端到端已含网络。': ('AA measures Groq SF '
                                                                                                '170.9: audio '
                                                                                                'duration/API response '
                                                                                                'time, seven-day '
                                                                                                'median. Consistent '
                                                                                                'via the turbo anchor '
                                                                                                'OpenASR RTFx 200.19. '
                                                                                                "This route's "
                                                                                                'end-to-end value '
                                                                                                'already includes '
                                                                                                'network time.',
                                                                                                'AAのGroq SF '
                                                                                                '170.9は音声長/API応答時間の7日中央値。turbo基準のOpenASR '
                                                                                                'RTFx '
                                                                                                '200.19と整合します。この経路の値は既に通信時間を含みます。'),
 'AA 实测': ('AA measurement', 'AA実測'),
 'AA 实测 MAI-Transcribe-2 WER 2.0%，榜内最佳': ('AA measures MAI-Transcribe-2 WER 2.0%, best on its leaderboard',
                                          'AA実測MAI-Transcribe-2 WER 2.0%、ランキング最高'),
 'AA 非流式榜单：MAI-Transcribe-2 WER 2.0%（榜内最佳；对照 Scribe v2 2.2 / Gemini 3.5 2.6 / GPT Transcribe 3.3）。OpenRouter 路由未验证。': ('AA '
                                                                                                                       'non-streaming: '
                                                                                                                       'MAI-Transcribe-2 '
                                                                                                                       'WER '
                                                                                                                       '2.0%, '
                                                                                                                       'best; '
                                                                                                                       'Scribe '
                                                                                                                       'v2 '
                                                                                                                       '2.2, '
                                                                                                                       'Gemini '
                                                                                                                       '3.5 '
                                                                                                                       '2.6, '
                                                                                                                       'GPT '
                                                                                                                       'Transcribe '
                                                                                                                       '3.3. '
                                                                                                                       'OpenRouter '
                                                                                                                       'route '
                                                                                                                       'unverified.',
                                                                                                                       'AA非ストリーミング：MAI-Transcribe-2 '
                                                                                                                       'WER '
                                                                                                                       '2.0%が最高。Scribe '
                                                                                                                       'v2 '
                                                                                                                       '2.2、Gemini '
                                                                                                                       '3.5 '
                                                                                                                       '2.6、GPT '
                                                                                                                       'Transcribe '
                                                                                                                       '3.3。OpenRouter経路は未検証。'),
 '多语言服务；AA 为英语集，中文未验证': ('Multilingual service; AA tests English, Chinese unverified', '多言語サービス。AAは英語評価で、中国語は未検証'),
 'AA 榜单仅英语。MAI-Transcribe-2 支持多语言转写（含说话人分离与字级时间戳），但未核到中文公开成绩；以英语榜最佳给通用档位 75（区间 70-80）。': ('AA covers English only. '
                                                                                          'MAI-Transcribe-2 supports '
                                                                                          'multilingual ASR with '
                                                                                          'speakers and character '
                                                                                          'timestamps, but no verified '
                                                                                          'Chinese public scores. '
                                                                                          'General tier 75 (70–80) '
                                                                                          'based on its English lead.',
                                                                                          'AAは英語のみ。MAI-Transcribe-2は話者と文字時刻を含む多言語ASRに対応しますが、中国語の公開成績は未確認。英語首位から一般水準75（70～80）と推定。'),
 '同中文口径，方言更未验证': ('Same Chinese basis; dialects even less verified', '中国語と同じ根拠、方言はさらに未検証'),
 '中文证据仅英语榜间接，方言单独未验证，档位估 70。': ('Chinese evidence is indirect from English; dialects unverified. Estimated tier 70.',
                                '中国語の根拠は英語からの間接推定で、方言は未検証。水準70。'),
 'AA 实测 Speed Factor 323.6（AA 榜第 2 快）': ('AA measured Speed Factor 323.6, second fastest',
                                         'AA実測Speed Factor 323.6、速度2位'),
 'AA 非流式：SF 323.6（含网络，7 天中位；对照 Deepgram Nova-3 543.8 榜首）。统一尺度 sqrt(379/418)≈95。OpenRouter 中转路由未实测——中转会增加延迟。': ('AA '
                                                                                                               'non-streaming '
                                                                                                               'SF '
                                                                                                               '323.6 '
                                                                                                               'includes '
                                                                                                               'network, '
                                                                                                               'seven-day '
                                                                                                               'median; '
                                                                                                               'Deepgram '
                                                                                                               'Nova-3 '
                                                                                                               'leads '
                                                                                                               'at '
                                                                                                               '543.8. '
                                                                                                               'Unified '
                                                                                                               'sqrt(379/418)≈95. '
                                                                                                               'OpenRouter '
                                                                                                               'relay '
                                                                                                               'route '
                                                                                                               'untested '
                                                                                                               'and '
                                                                                                               'may '
                                                                                                               'add '
                                                                                                               'latency.',
                                                                                                               'AA非ストリーミングSF '
                                                                                                               '323.6は通信込みの7日中央値（首位Deepgram '
                                                                                                               'Nova-3は543.8）。統一換算sqrt(379/418)≈95。OpenRouter中継経路は未測定で、追加の遅延が発生します。'),
 'OpenRouter 中转路由速度未实测': ('OpenRouter relay speed untested', 'OpenRouter中継速度は未測定'),
 'AA 实测 GPT Transcribe WER 3.3%': ('AA measured GPT Transcribe WER 3.3%', 'AA実測GPT Transcribe WER 3.3%'),
 'AA 非流式：OpenAI GPT Transcribe 3.3% / GPT-4o Transcribe 4.0% / mini 4.5%。当前默认 gpt-transcribe → 78。': ('AA '
                                                                                                      'non-streaming: '
                                                                                                      'GPT Transcribe '
                                                                                                      '3.3%, GPT-4o '
                                                                                                      'Transcribe '
                                                                                                      '4.0%, mini '
                                                                                                      '4.5%. Current '
                                                                                                      'default '
                                                                                                      'gpt-transcribe '
                                                                                                      'scores 78.',
                                                                                                      'AA非ストリーミング：GPT '
                                                                                                      'Transcribe '
                                                                                                      '3.3%、GPT-4o '
                                                                                                      'Transcribe '
                                                                                                      '4.0%、mini '
                                                                                                      '4.5%。現在の既定gpt-transcribeは78。'),
 '中文证据两极（4o 系）': ('Mixed Chinese evidence for the 4o family', '4o系列の中国語成績は両極端'),
 'GPT-4o-Transcribe 中文集：Fleurs-zh 2.44 优 / WS 15.30·32.27 差': ('GPT-4o-Transcribe Chinese: strong Fleurs-zh 2.44, weak '
                                                               'WS 15.30/32.27',
                                                               'GPT-4o-Transcribe中国語：Fleurs-zh 2.44は良好、WS '
                                                               '15.30/32.27は弱め'),
 'Qwen 官方表 GPT-4o-Transcribe 中文集两极分化（干净朗读近最佳、真实网络视频差）；gpt-transcribe 为更新型号（AA 英语更优）间接迁移。档位估 65（区间 55-80，视音频类型）。': ("Qwen's "
                                                                                                                   'GPT-4o-Transcribe '
                                                                                                                   'results '
                                                                                                                   'vary: '
                                                                                                                   'near-best '
                                                                                                                   'clean '
                                                                                                                   'read '
                                                                                                                   'speech, '
                                                                                                                   'weak '
                                                                                                                   'real '
                                                                                                                   'web '
                                                                                                                   'video. '
                                                                                                                   'gpt-transcribe '
                                                                                                                   'is '
                                                                                                                   'newer '
                                                                                                                   'and '
                                                                                                                   'better '
                                                                                                                   'on '
                                                                                                                   'AA '
                                                                                                                   'English, '
                                                                                                                   'providing '
                                                                                                                   'only '
                                                                                                                   'indirect '
                                                                                                                   'transfer. '
                                                                                                                   'Tier '
                                                                                                                   '65 '
                                                                                                                   '(55–80 '
                                                                                                                   'depending '
                                                                                                                   'on '
                                                                                                                   'audio '
                                                                                                                   'type).',
                                                                                                                   'Qwen表のGPT-4o-Transcribeは朗読で最高水準、実際のWeb動画では弱い成績。新しいgpt-transcribeはAA英語で改善していますが、転用は間接的です。音声種別に応じた水準65（55～80）。'),
 '中文证据有限': ('Limited Chinese evidence', '中国語の根拠は限定的'),
 '4o 系 KeSpeech 26.87%（Qwen 表）；方言偏弱': ("4o family KeSpeech 26.87% in Qwen's table; weak dialect performance",
                                       'Qwen表の4o系列KeSpeech 26.87%、方言は弱め'),
 'KeSpeech（方言）26.87 vs Qwen3 5.10；档位估 50。': ('KeSpeech 26.87 versus Qwen3 5.10; estimated tier 50.',
                                             'KeSpeech 26.87対Qwen3 5.10から、水準50と推定。'),
 'AA 实测 GPT Transcribe SF 40.8（含网络）': ('AA measured GPT Transcribe SF 40.8, including network',
                                       'AA実測GPT Transcribe SF 40.8、通信を含む'),
 'AA 非流式：GPT Transcribe 40.8 / GPT-4o 36.3 / mini 43.1。OpenAI 转写吞吐中档偏低。': ('AA non-streaming: GPT Transcribe 40.8, '
                                                                           'GPT-4o 36.3, mini 43.1. OpenAI '
                                                                           'transcription throughput is in the '
                                                                           'lower-middle tier.',
                                                                           'AA非ストリーミング：GPT Transcribe 40.8、GPT-4o '
                                                                           '36.3、mini '
                                                                           '43.1。OpenAI文字起こしのスループットは中水準の下側です。'),
 '公开基准换算': ('Published benchmark conversion', '公開ベンチマークの換算'),
 '独立评测（AA 实测）': ('Independent evaluation (AA measurement)', '独立評価（AA実測）'),
 '跨表校准估算': ('Cross-table calibration estimate', '表を跨ぐ較正推定'),
 'Artificial Analysis 非流式榜单（AA-WER v2；英语 ~8h：AgentTalk 50%+VoxPopuli 25%+Earnings22 25%，whisper 归一化；Speed Factor=音频时长/API 响应耗时，含网络，7 天中位）': ('Artificial '
                                                                                                                                             'Analysis '
                                                                                                                                             'non-streaming '
                                                                                                                                             'leaderboard: '
                                                                                                                                             'AA-WER '
                                                                                                                                             'v2, '
                                                                                                                                             'about '
                                                                                                                                             '8 '
                                                                                                                                             'h '
                                                                                                                                             'of '
                                                                                                                                             'English '
                                                                                                                                             '(AgentTalk '
                                                                                                                                             '50%, '
                                                                                                                                             'VoxPopuli '
                                                                                                                                             '25%, '
                                                                                                                                             'Earnings22 '
                                                                                                                                             '25%), '
                                                                                                                                             'whisper '
                                                                                                                                             'normalization. '
                                                                                                                                             'Speed '
                                                                                                                                             'Factor '
                                                                                                                                             '= '
                                                                                                                                             'audio '
                                                                                                                                             'duration/API '
                                                                                                                                             'response '
                                                                                                                                             'time, '
                                                                                                                                             'network '
                                                                                                                                             'included, '
                                                                                                                                             'seven-day '
                                                                                                                                             'median.',
                                                                                                                                             'Artificial '
                                                                                                                                             'Analysis非ストリーミング：AA-WER '
                                                                                                                                             'v2、英語約8時間（AgentTalk '
                                                                                                                                             '50%、VoxPopuli '
                                                                                                                                             '25%、Earnings22 '
                                                                                                                                             '25%）、whisper正規化。Speed '
                                                                                                                                             'Factorは音声長/API応答時間で、通信込みの7日中央値です。'),
 '中文普通话 4 集均值（AISHELL-1/2 + WenetSpeech net/meeting）': ('Mandarin 4-set mean (AISHELL-1/2 + WenetSpeech net/meeting)',
                                                        '普通話4セット平均（AISHELL-1/2 + WenetSpeech net/meeting）'),
 'FireRedASR2 官方 README 同表评测（各模型同一评测管线）': ('FireRedASR2 README same-table evaluation, with the same pipeline for all '
                                           'models',
                                           'FireRedASR2 READMEの同一表評価、全モデル同一手順'),
 'Doubao-ASR（API，未接入）': ('Doubao-ASR (API, not integrated)', 'Doubao-ASR（API、未接続）'),
 'Fun-ASR 7.7B（闭源，未开放）': ('Fun-ASR 7.7B (closed, unavailable)', 'Fun-ASR 7.7B（非公開、利用不可）'),
 'WenetSpeech test_net（网络视频口语）': ('WenetSpeech test_net (spoken web video)', 'WenetSpeech test_net（Web動画の会話）'),
 'Qwen3-ASR 官方 README 同表评测（vLLM/bfloat16/greedy，不指定语言）': ('Qwen3-ASR README same-table evaluation: '
                                                          'vLLM/bfloat16/greedy, no language specified',
                                                          'Qwen3-ASR README同一表評価：vLLM/bfloat16/greedy、言語指定なし'),
 'Whisper-large-v3（非本工程 turbo checkpoint）': ("Whisper-large-v3 (not this app's turbo checkpoint)",
                                             'Whisper-large-v3（このアプリのturboとは別）'),
 'WenetSpeech test_meeting（会议多人）': ('WenetSpeech test_meeting (multi-speaker meetings)',
                                    'WenetSpeech test_meeting（複数話者の会議）'),
 'FLEURS 中文（zh）': ('FLEURS Chinese (zh)', 'FLEURS中国語（zh）'),
 'Qwen3-ASR 官方 README 同表评测；funasr_nano 取该表复测值 3.51（Fun 自报 2.56 属另一协议，见技术说明）': ('Qwen3-ASR README same-table retest '
                                                                               "uses funasr_nano 3.51; Fun's 2.56 uses "
                                                                               'a different protocol. See details.',
                                                                               'Qwen3-ASR '
                                                                               'READMEのfunasr_nano再評価3.51を採用。Fun自己申告2.56は別手順です。詳細を参照。'),
 'AISHELL-1 test（SenseVoice 技术报告）': ('AISHELL-1 test (SenseVoice technical report)', 'AISHELL-1 test（SenseVoice技術報告）'),
 'FunAudioLLM SenseVoice 技术报告 Table 6；同表对照为 Whisper-Small/Large-v3': ('FunAudioLLM SenseVoice report Table 6; '
                                                                      'comparisons are Whisper-Small/Large-v3',
                                                                      'FunAudioLLM SenseVoice技術報告Table '
                                                                      '6、比較対象Whisper-Small/Large-v3'),
 'SenseVoice 论文 arXiv 2407.04051': ('SenseVoice paper arXiv 2407.04051', 'SenseVoice論文arXiv 2407.04051'),
 'Whisper-Small（对照）': ('Whisper-Small (reference)', 'Whisper-Small（比較対象）'),
 'Whisper-Large-v3（对照，非本工程 turbo checkpoint）': ("Whisper-Large-v3 (reference, not this app's turbo checkpoint)",
                                                'Whisper-Large-v3（比較対象、このアプリのturboとは別）'),
 'AISHELL-1 test（Paraformer 官方卡）': ('AISHELL-1 test (Paraformer official card)', 'AISHELL-1 test（Paraformer公式カード）'),
 'ModelScope 官方模型卡 w/o LM 解码；同表对照为 Espnet/WeNet 等学术系统': ('Official ModelScope card without LM; comparisons include '
                                                         'Espnet/WeNet research systems',
                                                         '公式ModelScopeカードのLMなしデコード。比較対象はEspnet/WeNetなどの研究システム'),
 'Paraformer-large ModelScope 模型卡': ('Paraformer-large ModelScope model card', 'Paraformer-large ModelScopeモデルカード'),
 'Wenet（对照，w/ LM 4.36）': ('WeNet (reference; with LM 4.36)', 'WeNet（比較対象、LMあり4.36）'),
 'AISHELL-1（Fun-ASR-Nano 官方卡）': ('AISHELL-1 (Fun-ASR-Nano official card)', 'AISHELL-1（Fun-ASR-Nano公式カード）'),
 'Fun-ASR-Nano-2512 HF 模型卡自报': ('Fun-ASR-Nano-2512 HF model card self-report', 'Fun-ASR-Nano-2512 HFモデルカードの自己申告'),
 'Fun-ASR-Nano-2512 模型卡': ('Fun-ASR-Nano-2512 model card', 'Fun-ASR-Nano-2512モデルカード'),
 'Fun-ASR 7.7B（闭源，对照）': ('Fun-ASR 7.7B (closed reference model)', 'Fun-ASR 7.7B（非公開の比較モデル）'),
 'AISHELL-4（长音频多说话人）': ('AISHELL-4 (long-form multi-speaker)', 'AISHELL-4（長時間・複数話者）'),
 'MOSS-Transcribe-Diarize 官方 README 同表客观评测（含说话人归属的联合转写）': ('MOSS-Transcribe-Diarize README same-table objective '
                                                           'evaluation, including speaker-attributed transcription',
                                                           'MOSS-Transcribe-Diarize READMEの同一表客観評価、話者付き文字起こしを含む'),
 'Alimeeting（会议多说话人）': ('Alimeeting (multi-speaker meetings)', 'Alimeeting（複数話者の会議）'),
 'MOSS-Transcribe-Diarize 官方 README 同表客观评测': ('MOSS-Transcribe-Diarize README same-table objective evaluation',
                                              'MOSS-Transcribe-Diarize READMEの同一表客観評価'),
 '中文方言 / 口音 19 集均值': ('Chinese dialect/accent 19-set mean', '中国語方言・アクセント19セット平均'),
 'FireRedASR2 官方 README 同表评测（粤语/四川/上海/吴语/闽南等 19 个公开集）': ('FireRedASR2 README same-table evaluation on 19 public sets, '
                                                         'including Cantonese, Sichuan, Shanghai, Wu and Minnan',
                                                         'FireRedASR2 README同一表評価、広東語・四川語・上海語・呉語・閩南語など19の公開セット'),
 'Qwen3-ASR 官方 README 同表评测（英语 WER，不代表中文 CER）': ('Qwen3-ASR README same-table evaluation; English WER is not Chinese '
                                                'CER',
                                                'Qwen3-ASR README同一表評価。英語WERは中国語CERを表しません'),
 'Hugging Face OpenASR 榜单口径（8 个英语集，whisper-normalizer）；数值为各官方模型卡自报的同榜结果': ('HF OpenASR protocol: 8 English sets with '
                                                                           'whisper-normalizer. Values are official '
                                                                           "model cards' self-reported results on that "
                                                                           'leaderboard.',
                                                                           'HF '
                                                                           'OpenASR基準：英語8セット、whisper-normalizer。各公式モデルカード掲載の同ランキング自己申告値です。'),
 '官方模型卡所载 OpenASR 结果（canary / GLM / whisper-turbo）': ("Official model cards' OpenASR results (canary / GLM / "
                                                      'whisper-turbo)',
                                                      '公式モデルカードのOpenASR結果（canary / GLM / whisper-turbo）'),
 'groq_api 与 whisper 共用同一 large-v3-turbo checkpoint，准确度随模型转移；托管侧服务速度另计，不互推。': ('groq_api and whisper share '
                                                                               'large-v3-turbo, so model accuracy '
                                                                               'transfers. Hosted service speed is '
                                                                               'separate and cannot be inferred from '
                                                                               'local speed.',
                                                                               'groq_apiとwhisperは同じlarge-v3-turboで、精度はモデルから転用します。ホスト側速度は別に扱い、相互に推定しません。'),
 'HF OpenASR 榜单 RTFx（英语）': ('HF OpenASR RTFx (English)', 'HF OpenASR RTFx（英語）'),
 '×实时': ('× real time', '倍リアルタイム'),
 'HF OpenASR 榜单统一评测环境；RTFx=1/RTF，越高越快': ('Unified HF OpenASR environment; RTFx=1/RTF, higher is faster',
                                         'HF OpenASR統一環境。RTFx=1/RTF、高いほど高速'),
 '榜单统一环境（A100 级）的参考吞吐，不代表本机速度；本机速度以“待本机实测”为准。': ("Reference throughput on the leaderboard's A100-class environment, "
                                                 'not your computer. Local speed remains unmeasured.',
                                                 'ランキングのA100級環境での参考スループットであり、手元のPCの速度ではありません。ローカル速度は未測定です。'),
 '强制对齐平均偏差 AAS · 中文（MFA Raw 标注）': ('Forced alignment mean deviation AAS, Chinese (MFA Raw labels)',
                                   '強制整列の平均偏差AAS、中国語（MFA Rawラベル）'),
 'Qwen3-ForcedAligner 官方 README 对齐评测；AAS 只衡量给定文本的对齐，不代表从零转写准确率，不与 CER/WER 混算': ('Qwen3-ForcedAligner README alignment '
                                                                                'evaluation. AAS measures alignment of '
                                                                                'given text, not ASR accuracy, and is '
                                                                                'not combined with CER/WER.',
                                                                                'Qwen3-ForcedAligner '
                                                                                'READMEの整列評価。AASは指定テキストの整列を測り、ASR精度ではなく、CER/WERとは混合しません。'),
 'NFA（对照）': ('NFA (reference)', 'NFA（比較対象）'),
 'Monotonic-Aligner / MFA（对照）': ('Monotonic-Aligner / MFA (reference)', 'Monotonic-Aligner / MFA（比較対象）'),
 'WhisperX 在该表中文列无数值（默认对齐模型不含中文）。': ('WhisperX has no Chinese value in this table because its default alignment model '
                                     'does not include Chinese.',
                                     'WhisperXは既定の整列モデルが中国語に非対応のため、この表に中国語の値がありません。')})

# Active workers and secondary panels.
STRINGS.update({'听到异常时再次点击标记；仅记录本应用状态，无录音，120 秒自动结束': ('Click again when you hear a problem. Records application state only, not '
                                        'audio; stops after 120 seconds.',
                                        '異常が聞こえたら再度クリック。アプリの状態のみを記録し、録音はしません。120秒で終了します。'),
 '标记声音异常': ('Mark Audio Issue', '音声異常を記録'),
 '声音异常标记已保存：{path}': ('Audio issue marker saved: {path}', '音声異常の記録を保存しました：{path}'),
 '词条': ('Term', '用語'),
 '别名': ('Aliases', '別名'),
 '优先': ('Priority', '優先度'),
 '约 {score}': ('Approx. {score}', '約 {score}'),
 '适合：{use}': ('Best for: {use}', '適した用途：{use}'),
 'FireRed 临时证据：{done}/{total} 批 · 音频 {start:.1f}–{end:.1f} 秒 · {text}': ('FireRed provisional evidence: {done}/{total} '
                                                                         'batches · Audio {start:.1f}–{end:.1f} s · '
                                                                         '{text}',
                                                                         'FireRed仮結果：{done}/{total}バッチ · 音声 '
                                                                         '{start:.1f}～{end:.1f}秒 · {text}'),
 'API 返回：{done}/{total} 批 · 临时转写 {count} 条': ('API results: {done}/{total} batches · Provisional subtitles: {count}',
                                              'API応答：{done}/{total}バッチ · 仮字幕 {count}件'),
 '已分析 {start:.1f}–{end:.1f} 秒': ('Analyzed {start:.1f}–{end:.1f} s', '{start:.1f}～{end:.1f}秒を解析済み'),
 '复用匹配音频的缓存': ('Reusing cache for matching audio', '一致する音声のキャッシュを再利用'),
 '最近音频 {start:.1f}–{end:.1f} 秒': ('Latest audio {start:.1f}–{end:.1f} s', '最新の音声 {start:.1f}～{end:.1f}秒'),
 '收口说话人交接边界': ('Refine speaker handoff boundaries', '話者交代の境界を調整'),
 '{name}\n{count} 条字幕 · {duration}\n{status}': ('{name}\nSubtitles: {count} · {duration}\n{status}',
                                                '{name}\n字幕 {count}件 · {duration}\n{status}'),
 '编辑 {time}': ('Edited {time}', '編集 {time}'),
 '视频预览不可用': ('Video preview unavailable', '動画プレビューを利用できません'),
 '播放已恢复': ('Playback resumed', '再生を再開しました'),
 'AI 断句进行中…': ('AI segmentation in progress…', 'AI分割を処理中…'),
 'AI 断句：没有可处理的新字幕': ('AI segmentation: no new subtitles to process', 'AI分割：処理できる新しい字幕がありません'),
 '字幕数': ('Subtitles', '字幕数'),
 '总时长': ('Total duration', '合計時間'),
 '显示 / 原始标签': ('Display / Original Label', '表示名 / 元のラベル'),
 '段数 / 时长': ('Segments / Duration', '区間数 / 時間'),
 '时间分布（分:秒）': ('Time Distribution (min:sec)', '時間分布（分:秒）'),
 '代表片段': ('Sample Segments', '代表区間'),
 '用途': ('Usage', '用途'),
 '正在离线测量重叠 HTML 主题装饰…': ('Measuring overlapping HTML theme decorations offline…', 'HTMLテーマ装飾の重なりをオフラインで計測中…'),
 '工程已改变，主题测量结果未应用；请重试。': ('The project changed, so the measurements were not applied. Please retry.',
                          'プロジェクトが変わったため計測結果を適用しませんでした。再試行してください。'),
 '阶段 {stage} 已完成，正在准备后续资源': ('Stage {stage} completed; preparing the next resources', '{stage}が完了しました。次の処理を準備中'),
 '{message} · 距最近有效结果 {seconds} 秒': ('{message} · {seconds} s since the last valid result',
                                     '{message} · 最後の有効な結果から{seconds}秒'),
 '{message} · 尚无转写结果': ('{message} · No transcription results yet', '{message} · 文字起こし結果はまだありません'),
 '正在加载说话人模型': ('Loading speaker model', '話者モデルを読み込み中'),
 '模型已加载，开始分析': ('Model loaded; starting analysis', 'モデル読込完了、解析を開始'),
 '正在分析说话人': ('Analyzing speakers', '話者を解析中'),
 '音频分析完成': ('Audio analysis completed', '音声解析が完了'),
 '正在匹配字幕标签': ('Matching subtitle labels', '字幕ラベルを照合中'),
 '说话人结果已合并，身份待确认': ('Speaker results merged; identities need review', '話者結果を統合しました。話者の確認が必要です'),
 '分析失败，文字已保留': ('Analysis failed; text preserved', '解析に失敗しました。テキストは保持されています'),
 'API请求进行中，等待真实返回': ('API request in progress; waiting for a response', 'APIリクエストを送信中、応答を待っています'),
 '模型加载完成，等待推理结果': ('Model loaded; waiting for inference results', 'モデル読込完了、推論結果を待っています'),
 '设备与精度已确认': ('Device and precision confirmed', 'デバイスと精度を確認済み'),
 '已降低批次并发，重试当前批次': ('Reduced concurrency; retrying the current batch', '並列数を減らし、現在のバッチを再試行中'),
 '当前字幕尚未应用方案': ('No design applied to this subtitle', 'この字幕にはデザインが未適用です'),
 '请先在时间轴选中字幕，再应用已采用的方案': ('Select a subtitle in the timeline to apply the chosen design',
                          'タイムラインで字幕を選択して、採用したデザインを適用してください'),
 '应用到当前字幕': ('Apply to Current Subtitle', '現在の字幕に適用'),
 '完整候选并发：{count}': ('Concurrent full candidates: {count}', '完全候補の並列数：{count}'),
 '结构化输出': ('Structured output', '構造化出力'),
 '文字上下文': ('Text context', 'テキストの文脈'),
 '阿里云百炼（保留）': ('Alibaba Cloud DashScope (legacy)', 'Alibaba Cloud DashScope（旧設定）'),
 '未配置': ('Not configured', '未設定'),
 '无法分析': ('Analysis unavailable', '解析できません'),
 '✓ 弹幕 XML': ('✓ Danmaku XML', '✓ 弾幕XML'),
 '弹幕 XML 未匹配': ('No matching danmaku XML', '一致する弾幕XMLなし'),
 '跟随全局（当前 {name} · {model}）': ('Use global settings ({name} · {model})', '全体設定を使用（{name} · {model}）'),
 '默认（{model}）': ('Default ({model})', '既定（{model}）'),
 '{service}（未配置）': ('{service} (not configured)', '{service}（未設定）'),
 '{service}（无联网）': ('{service} (no web access)', '{service}（Webアクセスなし）'),
 '自然': ('Natural', '自然'),
 '保守': ('Conservative', '控えめ'),
 '紧凑': ('Compact', '短め'),
 '检测已取消，请在当前工程重新检测。': ('Detection canceled. Run detection again in the current project.',
                       '検出をキャンセルしました。現在のプロジェクトで再実行してください。'),
 '入点 {start}  →  出点 {end} · 时长 {duration}': ('In {start}  →  Out {end} · Duration {duration}',
                                             'イン点 {start} → アウト点 {end} · 長さ {duration}'),
 '百炼 generation 接口支持 forced_search': ('The DashScope generation API supports forced_search',
                                      'DashScope generation APIはforced_searchに対応'),
 '全部分类': ('All categories', 'すべてのカテゴリ'),
 '其他': ('Other', 'その他'),
 '技能': ('Skills', 'スキル'),
 '游戏术语': ('Game terms', 'ゲーム用語'),
 '角色': ('Characters', 'キャラクター'),
 '重新应用到{target}': ('Reapply to {target}', '{target}に再適用'),
 '应用到{target}': ('Apply to {target}', '{target}に適用'),
 '重试应用到{target}': ('Retry Applying to {target}', '{target}への適用を再試行'),
 '当前字幕': ('Current Subtitle', '現在の字幕'),
 '该说话人字幕': ("This Speaker's Subtitles", 'この話者の字幕'),
 '全部字幕': ('All Subtitles', 'すべての字幕'),
 '正在应用到当前字幕…': ('Applying to the current subtitle…', '現在の字幕に適用中…'),
 '已采用方向 · 正在校验并应用…': ('Direction selected · Validating and applying…', '方向性を採用済み · 検証して適用中…'),
 '正在应用…': ('Applying…', '適用中…'),
 '已应用到当前字幕 · 可编辑主题': ('Applied to the current subtitle · Editable theme', '現在の字幕に適用済み · 編集可能なテーマ'),
 '原设计对象已改变或删除 · 选中字幕后可重试应用': ('The original target changed or was deleted · Select a subtitle to retry',
                              '元の対象が変更・削除されました · 字幕を選んで再試行できます'),
 '可编辑主题 · 拖动字幕移动，拖动角点等比缩放；双击改字。': ('Editable theme · Drag to move, drag a corner to scale, double-click to edit text.',
                                   '編集可能なテーマ · ドラッグで移動、角をドラッグで拡縮、ダブルクリックで文字を編集。'),
 '流畅预览准备中 {progress}，完成后自动使用。': ('Preparing smooth preview {progress}; it will be used automatically when ready.',
                                 'スムーズなプレビューを準備中 {progress}。完了後に自動で使用します。'),
 '流畅预览已就绪 · 文字仍可编辑': ('Smooth preview ready · Text remains editable', 'スムーズなプレビュー準備完了 · テキストは編集できます'),
 '流畅预览未就绪，当前使用实时预览。': ('Smooth preview unavailable; using live preview.', 'スムーズなプレビューが未準備のため、ライブプレビューを使用します。'),
 'AI 断句中… {value0} 条{value1}': ('AI segmentation… Subtitles: {value0} {value1}', 'AI分割中… 字幕{value0}件 {value1}'),
 '（全工程）': ('(whole project)', '（プロジェクト全体）'),
 '（选中范围）': ('(selection)', '（選択範囲）'),
 'AI 断句失败，已保留原文：{value0}': ('AI segmentation failed; original text preserved: {value0}',
                            'AI分割に失敗しました。原文は保持されています：{value0}'),
 'AI 断句完成：拆分 {value0} 条 · 节奏空格 {value1} 条 · 拒绝 {value2}{value3}': ('AI segmentation complete: split {value0} · Spacing '
                                                                   '{value1} · Rejected {value2}{value3}',
                                                                   'AI分割完了：分割{value0}件 · 間隔調整{value1}件 · '
                                                                   '却下{value2}件{value3}'),
 'AI 断句完成：无需调整 {value0}': ('AI segmentation complete: no changes needed {value0}', 'AI分割完了：調整は不要です {value0}'),
 '（{count} 条建议被护栏拒绝）': ('({count} suggestions rejected by validation)', '（検証により{count}件の提案を却下）'),
 ' · {count} 条时间证据不足，未拆分': (' · {count} left unsplit due to insufficient timing evidence',
                            ' · 時刻の根拠が不足する{count}件は分割していません'),
 'AI 断句：{value0} 条缺少可匹配的字词边界，保留原字幕，请试听后手动切分': ('AI segmentation: {value0} subtitles lack matching word boundaries. '
                                               'Originals preserved; listen and split manually.',
                                               'AI分割：{value0}件に一致する単語境界がありません。元の字幕を保持しています。試聴して手動で分割してください。'),
 '主题装饰测量完成：{value0} 个，{value1:.1f} 秒；改字或样式后需重新测量。': ('Theme measurements complete: {value0} items in {value1:.1f} s. '
                                                     'Remeasure after changing text or style.',
                                                     'テーマ装飾の計測完了：{value0}件、{value1:.1f}秒。文字やスタイルを変更したら再計測してください。'),
 '主题装饰测量失败：{value0}；保持原位置，可手动调整。': ('Theme measurement failed: {value0}. Positions are unchanged; adjust them '
                                    'manually.',
                                    'テーマ計測に失敗しました：{value0}。位置は保持しています。手動で調整できます。'),
 '字幕文本 + 时间轴': ('Subtitle text + timestamps', '字幕テキストと時刻'),
 '字幕文本 + 说话人标签': ('Subtitle text + speaker labels', '字幕テキストと話者ラベル'),
 '字幕文本 + 时间轴 + 说话人标签': ('Subtitle text + timestamps + speaker labels', '字幕テキスト、時刻、話者ラベル'),
 '转写 + 说话人分析': ('Transcription + speaker analysis', '文字起こしと話者解析'),
 '可独立转写': ('Standalone transcription supported', '単独で文字起こし可能'),
 '不能独立转写': ('Cannot transcribe independently', '単独の文字起こしは不可'),
 '需要已有文本': ('Requires existing text', '既存テキストが必要'),
 '中文通用识别': ('General Chinese transcription', '中国語の一般文字起こし'),
 '中文长音频 / 多人': ('Long-form Chinese / multi-speaker', '中国語の長時間音声・複数話者'),
 '中文方言 / 口音': ('Chinese dialects / accents', '中国語の方言・アクセント'),
 '字幕时间轴 / 强制对齐': ('Subtitle timing / forced alignment', '字幕タイミング・強制整列'),
 '官方同表评测': ('Official same-table evaluation', '公式の同一表評価'),
 '官方模型卡自报': ('Official model card self-report', '公式モデルカードの自己申告'),
 '独立评测（榜单口径，官方卡自报）': ('Independent leaderboard evaluation (model-card self-report)', '独立ランキング評価（公式カードの自己申告）'),
 '官方技术报告': ('Official technical report', '公式技術報告')})

# Existing translate() sites and model-detail headings.
STRINGS.update({'给参考': ('as a reference', 'を参考に使用'),
 '暂无速度数据': ('No speed data', '速度データなし'),
 '暂无可比数据': ('No comparable data', '比較可能なデータなし'),
 '2ByteASR 参考指数：1–100 相对选型参考，不是识别正确率。': ('2ByteASR reference index: a relative 1–100 selection guide, not recognition '
                                         'accuracy.',
                                         '2ByteASR参考指数：選択のための相対的な1～100の指標で、認識の正解率ではありません。'),
 '（托管路由未验证）': ('(hosted route unverified)', '（ホスト経路は未検証）'),
 '综合直接评测、跨表校准（经共同参照模型）与间接证据档位的 1–100 选型参考；100 = 当前参考版本与适用场景内的相对领先，不是识别正确率。': ('A 1–100 selection reference combining '
                                                                              'direct evaluations, calibration through '
                                                                              'shared reference models and indirect '
                                                                              'tier estimates. 100 means relatively '
                                                                              'leading for this reference version and '
                                                                              'scenario, not a percentage of correct '
                                                                              'recognition.',
                                                                              '直接評価、共通モデルを介した表間較正、間接的な水準推定を組み合わせた1～100の選択用参考値です。100は現在の参考版と対象用途での相対的な上位を意味し、認識正解率ではありません。'),
 '2ByteASR 参考评分及推导': ('2ByteASR Reference Scores and Derivation', '2ByteASR参考スコアと算出根拠'),
 '卡片分数 = 同组相对指数：round(100 × sqrt(组内最佳 / 当前值))（错误率类），100 = 该基准组相对最佳，不是识别正确率百分比。': ('Card score = round(100 × sqrt(group '
                                                                                  'best / current value)) for error '
                                                                                  'metrics. 100 is the best within '
                                                                                  'that benchmark group, not a '
                                                                                  'percentage of correct recognition.',
                                                                                  'カードの誤り率スコアはround(100 × sqrt(グループ最良値 '
                                                                                  '/ '
                                                                                  '現在値))です。100は同条件グループの最高値で、認識正解率ではありません。'),
 '评分依据（同组相对分）': ('Score Basis (Within-Group Relative Index)', '評価根拠（同条件グループ内の相対指数）'),
 '估算分（约）：依据间接证据的档位/校准推导，不是官方同台成绩。': ('Approximate score: derived from indirect tier evidence or calibration, not an '
                                     'official same-condition measurement.',
                                     '概算スコア：間接的な水準・較正から算出したもので、公式の同条件実測ではありません。'),
 '换算分：来自公开评测表的相对换算。': ('Converted score: a relative conversion from a published evaluation table.',
                       '換算スコア：公開評価表から相対的に算出した値です。'),
 '核实 2026-09-18': ('Verified 2026-09-18', '2026-09-18確認'),
 '未单独收录，按预设默认': ('is not listed separately; using the preset default', 'は個別未掲載のため、プリセットの既定モデル'),
 '同组相对指数：100 = 该基准组相对最佳，不是识别正确率百分比。': ('Within-group index: 100 is the best in this benchmark group, not recognition '
                                       'accuracy.',
                                       'グループ内相対指数：100はこの評価グループの最高値で、認識正解率ではありません。'),
 '暂无公开速度数据 · 待本机实测': ('No published speed data · Local measurement pending', '公開速度データなし · ローカル測定待ち'),
 '暂无同组可比数据': ('No comparable within-group data', '同条件で比較可能なデータなし'),
 '不把缺失数据换算成分数；可切换“排序与筛选”中的比较场景。': ('Missing data is not converted into a score. Change the comparison scenario under '
                                   'Sort & Filter.',
                                   '欠測値にはスコアを付けません。「並べ替えと絞り込み」で比較用途を変更できます。'),
 '分数绑定「比较场景 + 基准组 + 参照集合 + 公式版本」，与搜索/筛选/安装状态无关。': ('Scores depend on the scenario, benchmark group, reference set and '
                                                   'formula version, not search, filtering or installation status.',
                                                   'スコアは用途、評価グループ、参照集合、算出式の版に基づき、検索・絞り込み・インストール状態には依存しません。'),
 '该模型暂无同组可比数据（没有同来源、同协议的公开横评表覆盖它），因此不显示分数，避免把占位值伪装成评测结论。': ('No public same-source, same-protocol comparison covers '
                                                            'this model. No score is shown, so a placeholder cannot be '
                                                            'mistaken for an evaluation result.',
                                                            'このモデルを含む同一出典・同一手順の公開比較がありません。仮の値を評価結果に見せないため、スコアは表示しません。'),
 '不显示分数（该表仅此一家来源，无法横比）': ('No score: only one source in this table, so no cross-model comparison',
                          'スコアなし：この表には1モデルのみで、モデル間比較はできません'),
 '官方参考 RTF': ('Official reference RTF', '公式参考RTF'),
 '不同硬件不互比': ('Different hardware is not comparable', '異なるハードウェアは比較不可'),
 '依据类型': ('Evidence Type', '根拠の種類'),
 '推导': ('Derivation', '算出根拠'),
 '已按当前型号': ('Using the current model', '現在のモデルを使用'),
 '不支持该场景语言': ('Scenario language unsupported', 'この用途の言語は非対応'),
 '该模型在当前场景明确不支持，不给参考分。': ('This model explicitly does not support the selected language; no reference score is '
                          'assigned.',
                          '選択した用途の言語には明確に非対応のため、参考スコアを付けません。'),
 '暂无同组可比数据：没有可与该模型直接比较的同协议公开评测。': ('No comparable data: no public evaluation uses the same protocol for this model and '
                                   'its peers.',
                                   '比較可能なデータなし：このモデルと他モデルを同じ手順で評価した公開資料がありません。'),
 '下载中…': ('Downloading…', 'ダウンロード中…'),
 '2ByteASR 工作流选型评价，并非官方统一跑分。': ('2ByteASR workflow selection guidance, not a unified official benchmark.',
                                '2ByteASRの処理構成を選ぶための評価で、公式の統一ベンチマークではありません。'),
 '参考版本': ('Reference Version', '参考版'),
 '参照目录固定，不随搜索/筛选/安装态变化': ('The reference catalog is fixed and does not change with search, filtering or installation '
                          'status',
                          '参照カタログは固定で、検索・絞り込み・インストール状態では変わりません'),
 '技术说明': ('Technical Details', '技術説明'),
 '当前型号': ('Current Model', '現在のモデル'),
 '基准组': ('Benchmark Group', '評価グループ'),
 '原始指标': ('Raw Metric', '元の指標'),
 '核实日期': ('Verification Date', '確認日'),
 '公式': ('Formula', '算出式'),
 '另有同表数据': ('Additional same-table data', '同一表の追加データ'),
 '当前解析型号': ('Resolved Model', '解決されたモデル'),
 '暂无参考数据': ('No reference data', '参考データなし'),
 '评分': ('Score', 'スコア'),
 '缺口': ('Evidence Gap', '不足している根拠'),
 '同表外部参照': ('External References in the Same Table', '同一表の外部比較対象'),
 '备注': ('Notes', '備考'),
 '依据': ('Basis', '根拠'),
 '正在扫描…': ('Scanning…', 'スキャン中…'),
 '没有符合搜索条件的记录': ('No records match your search', '検索に一致する記録がありません'),
 '换个关键词，或清空搜索查看全部任务记录。': ('Try another keyword, or clear the search to view all task records.',
                          '別のキーワードを試すか、検索を消してすべてのタスクを表示してください。'),
 'Google Antigravity · 登录态由官方 CLI 管理': ('Google Antigravity · Sign-in is managed by the official CLI',
                                        'Google Antigravity · ログイン状態は公式CLIが管理'),
 'Grok Account · OAuth 由官方 CLI 管理': ('Grok Account · OAuth is managed by the official CLI',
                                     'Grok Account · OAuthは公式CLIが管理')})

# Confirmation and diagnostic dialogs.
STRINGS.update({'当前 API 密钥无效或未授权。\n基础建词仍可继续使用，结果已保留。': ('The API key is invalid or unauthorized.\n'
                                         'Basic term building remains available and results have been preserved.',
                                         'APIキーが無効、または権限がありません。\n基本の用語生成は利用でき、結果は保持されています。'),
 '保存工程修改': ('Save Project Changes', 'プロジェクトの変更を保存'),
 '{value0}前是否保存当前工程修改？': ('Save the current project before {value0}?', '{value0}前に現在のプロジェクトの変更を保存しますか？'),
 '已导出并验证 {value0} 个文件。\n{value1}': ('Exported and verified {value0} files.\n{value1}',
                                    '{value0}ファイルを書き出し、検証しました。\n{value1}'),
 '导出字幕失败': ('Subtitle Export Failed', '字幕の書き出しに失敗'),
 '媒体：{value0}\n分辨率：{value1}\n视频时长：{value2}\n字幕条数：{value3}\n最后编辑：{value4}\n工程路径：{value5}': ('Media: {value0}\n'
                                                                                           'Resolution: {value1}\n'
                                                                                           'Duration: {value2}\n'
                                                                                           'Subtitles: {value3}\n'
                                                                                           'Last edited: {value4}\n'
                                                                                           'Project path: {value5}',
                                                                                           'メディア：{value0}\n'
                                                                                           '解像度：{value1}\n'
                                                                                           '長さ：{value2}\n'
                                                                                           '字幕数：{value3}\n'
                                                                                           '最終編集：{value4}\n'
                                                                                           'プロジェクトパス：{value5}'),
 '删除所选工程': ('Delete Selected Projects', '選択したプロジェクトを削除'),
 '确定删除 {value0} 个工程？\n\n{value1}\n\n仅移除工程文件（.2byteproj）与最近记录，源媒体和识别缓存不受影响。': ('Delete selected projects ({value0})?\n'
                                                                              '\n'
                                                                              '{value1}\n'
                                                                              '\n'
                                                                              'Only project files (.2byteproj) and '
                                                                              'recent entries will be removed. Source '
                                                                              'media and recognition caches are '
                                                                              'preserved.',
                                                                              '{value0}件のプロジェクトを削除しますか？\n'
                                                                              '\n'
                                                                              '{value1}\n'
                                                                              '\n'
                                                                              '削除するのはプロジェクトファイル（.2byteproj）と履歴のみです。元のメディアと認識キャッシュは保持します。'),
 '部分工程未能删除': ('Some Projects Could Not Be Deleted', '一部のプロジェクトを削除できませんでした'),
 '{value0} 个工程文件删除失败（可能正被占用）：\n{value1}': ('Could not delete {value0} project files; they may be in use:\n{value1}',
                                           '{value0}件のプロジェクトファイルを削除できません。使用中の可能性があります：\n{value1}'),
 '确定删除 {value0}？': ('Delete {value0}?', '{value0}を削除しますか？'),
 '先导入媒体': ('Import Media First', '先にメディアを読み込む'),
 '识别字幕需要当前工程中的视频或音频。请先导入媒体。': ('Transcription requires video or audio in the current project. Import media first.',
                               '文字起こしには現在のプロジェクトに動画または音声が必要です。先にメディアを読み込んでください。'),
 '请先保存工程': ('Save the Project First', '先にプロジェクトを保存'),
 '保存工程后才能把识别结果写回同一个工程。': ('Save the project before writing recognition results back to it.',
                          '認識結果を同じプロジェクトへ書き戻すには、先に保存してください。'),
 '先加载媒体': ('Load Media First', '先にメディアを開く'),
 '请先拖入媒体或 .2byteproj，再导入字幕。': ('Drop media or a .2byteproj file before importing subtitles.',
                               '字幕を読み込む前に、メディアまたは.2byteprojをドロップしてください。'),
 '导入字幕失败': ('Subtitle Import Failed', '字幕の読み込みに失敗'),
 '正式保存  {value0}\n自动恢复  {value1}\n\n请选择要打开的版本。': ('Saved version  {value0}\n'
                                                  'Recovery version  {value1}\n'
                                                  '\n'
                                                  'Choose which version to open.',
                                                  '保存済み版  {value0}\n自動復元版  {value1}\n\n開くバージョンを選んでください。'),
 '请选择恢复自动保存、打开正式保存，或删除恢复点。': ('Restore autosave, open the saved version, or delete the recovery point.',
                              '自動保存から復元、保存済み版を開く、復元ポイントを削除のいずれかを選んでください。'),
 '无法打开项目': ('Cannot Open Project', 'プロジェクトを開けません'),
 '输出文件已存在': ('Output File Already Exists', '出力ファイルが既に存在します'),
 '是否在压制成功后替换现有文件？\n\n{value0}': ('Replace the existing file after encoding succeeds?\n\n{value0}',
                                 'エンコード成功後に既存ファイルを置き換えますか？\n\n{value0}'),
 '压制失败': ('Encoding Failed', 'エンコードに失敗'),
 '合并说话人': ('Merge Speakers', '話者を統合'),
 '将 {value0} 的全部 Cue 合并到 {value1}？\n此操作可用 Ctrl+Z 撤销。': ('Merge all subtitles from {value0} into {value1}?\n'
                                                        'You can undo this with Ctrl+Z.',
                                                        '{value0}の全字幕を{value1}へ統合しますか？\nCtrl+Zで元に戻せます。'),
 '无字幕': ('No Subtitles', '字幕なし'),
 '{value0} 还没有任何字幕，无法试听。': ('{value0} has no subtitles to preview.', '{value0}には字幕がなく、試聴できません。'),
 '无需修改': ('No Changes Needed', '変更は不要です'),
 '导入失败': ('Import Failed', '読み込みに失敗'),
 '请先打开字幕工程。': ('Open a subtitle project first.', '先に字幕プロジェクトを開いてください。'),
 '当前工程没有可管理的说话人。': ('This project has no speakers to manage.', 'このプロジェクトには管理できる話者がいません。'),
 '{value0}\n\n可稍后重试，或打开发布页手动下载。': ('{value0}\n\nRetry later, or open the releases page to download manually.',
                                   '{value0}\n\n後で再試行するか、リリースページから手動でダウンロードしてください。'),
 '{value0}\n\n{value1}\n\n处理完成后请关闭并重新打开 2ByteASR。\nNVIDIA 驱动：https://www.nvidia.com/Download/index.aspx': ('{value0}\n'
                                                                                                           '\n'
                                                                                                           '{value1}\n'
                                                                                                           '\n'
                                                                                                           'Close and '
                                                                                                           'reopen '
                                                                                                           '2ByteASR '
                                                                                                           'after '
                                                                                                           'completing '
                                                                                                           'these '
                                                                                                           'steps.\n'
                                                                                                           'NVIDIA '
                                                                                                           'drivers: '
                                                                                                           'https://www.nvidia.com/Download/index.aspx',
                                                                                                           '{value0}\n'
                                                                                                           '\n'
                                                                                                           '{value1}\n'
                                                                                                           '\n'
                                                                                                           '対処後は2ByteASRを終了して再起動してください。\n'
                                                                                                           'NVIDIAドライバー：https://www.nvidia.com/Download/index.aspx'),
 '诊断代码：{value0}\nGPU：{value1}\n显存：{value2} MB\nNVIDIA 驱动：{value3}\nPyTorch：{value4}\nPyTorch CUDA 构建：{value5}': ('Diagnostic '
                                                                                                                 'code: '
                                                                                                                 '{value0}\n'
                                                                                                                 'GPU: '
                                                                                                                 '{value1}\n'
                                                                                                                 'VRAM: '
                                                                                                                 '{value2} '
                                                                                                                 'MB\n'
                                                                                                                 'NVIDIA '
                                                                                                                 'driver: '
                                                                                                                 '{value3}\n'
                                                                                                                 'PyTorch: '
                                                                                                                 '{value4}\n'
                                                                                                                 'PyTorch '
                                                                                                                 'CUDA '
                                                                                                                 'build: '
                                                                                                                 '{value5}',
                                                                                                                 '診断コード：{value0}\n'
                                                                                                                 'GPU：{value1}\n'
                                                                                                                 'VRAM：{value2} '
                                                                                                                 'MB\n'
                                                                                                                 'NVIDIAドライバー：{value3}\n'
                                                                                                                 'PyTorch：{value4}\n'
                                                                                                                 'PyTorch '
                                                                                                                 'CUDAビルド：{value5}'),
 '重新加载将载入新字幕并丢弃这些编辑；保留编辑则新字幕已写入工程文件，稍后重新打开工程即可加载。': ('Reloading loads the new subtitles and discards these edits. If '
                                                     'you keep editing, the new subtitles remain in the project file '
                                                     'and will load when you reopen it.',
                                                     '再読み込みすると新しい字幕を開き、現在の編集を破棄します。編集を続けた場合、新しい字幕はファイルに保存されており、後でプロジェクトを開き直すと読み込まれます。'),
 '请先到模型工坊下载并选择模型，或配置在线 ASR API。': ('Download and select a model in Model Workshop, or configure an online ASR API.',
                                   'モデル工房でモデルをダウンロードして選ぶか、オンラインASR APIを設定してください。')})
STRINGS.update({
    '音频类型': ('Audio Type', '音声の種類'),
    '许可协议': ('License', 'ライセンス'),
    '论文': ('Paper', '論文'),
    '实际断句模型：{provider} / {model} · 说话人区分：{state}': ('Active segmentation model: {provider} / {model} · Speaker diarization: {state}', '使用中の分割モデル：{provider} / {model} · 話者分離：{state}'),
    '已开启：{speaker}': ('On: {speaker}', 'オン：{speaker}'),
    '已接收 {count} 条': ('Received subtitles: {count}', '字幕{count}件を受信'),
    '{stage} · 本次配置不适用': ('{stage} · Not applicable to this configuration', '{stage} · 現在の設定には適用されません'),
    '{stage} · {seconds:.1f} 秒': ('{stage} · {seconds:.1f} s', '{stage} · {seconds:.1f}秒'),
    '复用 {stage}，跳过重复计算': ('Reusing {stage}; skipping repeated computation', '{stage}を再利用し、重複する計算を省略'),
    '{count} 个云端批次，最多 {workers} 路': ('Cloud batches: {count} · Up to {workers} concurrent requests', 'クラウド{count}バッチ · 最大{workers}並列'),
    '{done} / {total} 完成 · {seconds:.1f} 秒': ('{done} / {total} completed · {seconds:.1f} s', '{done} / {total}完了 · {seconds:.1f}秒'),
    '已完成 {name}': ('Completed {name}', '{name}を完了'),
    '任务配置': ('Task configuration', 'タスク設定'),
    '最终字幕': ('Final subtitles', '確定字幕'),
    '临时转写（待校对）': ('Provisional transcription (review pending)', '仮の文字起こし（確認待ち）'),
    '检测到断句调序，已从校对源段安全重建并重新校验': ('Segmentation reordered text; safely rebuilt from reviewed source segments and validated again', '分割による並べ替えを検出し、確認済み原文区間から再構築して再検証しました'),
    '已发出安全取消请求，正在等待当前阶段收尾': ('Safe cancellation requested; waiting for the current stage to finish', '安全なキャンセルを要求しました。現在の処理段階の終了を待っています'),
    '缺失 · {name} / {id}': ('Missing · {name} / {id}', '見つかりません · {name} / {id}'),
    '并入 {name}': ('Merge into {name}', '{name}に統合'),
    '说话人分析失败，已保留字幕文字。{error} 可用下方重新识别入口重试。': ('Speaker analysis failed; subtitle text was preserved. {error} Use the recognition action below to retry.', '話者分析に失敗しました。字幕の本文は保持されています。{error} 下の再認識ボタンから再試行できます。'),
    '{name}\n原始 {label}': ('{name}\nOriginal {label}', '{name}\n元のラベル {label}'),
    '{count} 段 / {seconds:.2f}s': ('Segments: {count} / {seconds:.2f}s', '{count}区間 / {seconds:.2f}秒'),
    '原始 {raw} → {name}': ('Original {raw} → {name}', '元のラベル {raw} → {name}'),
    '{name}（已隐藏）': ('{name} (hidden)', '{name}（非表示）'),
    '公式': ('Formula', '計算式'),
    '（{count} 条已存在，未重复入库）': (' (already present and skipped: {count})', '（{count}件は登録済みのため追加を省略）'),
    '；{count} 条保存失败，请在预览中重试': ('; save failed for {count} entries; retry in the preview', '。{count}件を保存できませんでした。プレビューから再試行してください'),
    '；撤销记录未保存': ('; undo history was not saved', '。元に戻す履歴は保存されませんでした'),
    'Windows 音量混音器已将 2ByteASR 音频会话静音，请在系统混音器中取消静音；程序内播放音量正常。': ('Windows has muted 2ByteASR. Unmute it in Volume Mixer; the in-app volume is normal.', 'Windowsの音量ミキサーで2ByteASRがミュートされています。ミュートを解除してください。アプリ内の音量は正常です。'),
    '音频输出设备不可用，请检查设备后暂停/继续': ('Audio output is unavailable. Check your device, then pause and resume playback.', '音声出力デバイスを利用できません。デバイスを確認し、再生を一時停止してから再開してください。'),
    '… 以及另外 {count} 个': ('… and {count} more', '…ほか{count}件'),
    '尚无符合条件的真实事件。': ('No matching events yet.', '条件に一致するイベントはまだありません。'),
    '应用': ('Application', 'アプリ'),
    '服务端': ('Service', 'サービス'),
    'CLI错误输出': ('CLI error output', 'CLIエラー出力'),
    '页面响应': ('Page response', 'ページの応答'),
    '候选': ('Candidate', '候補'),
    '入点必须早于出点，不能导出零时长或反向范围。': ('The in point must precede the out point. Empty or reversed ranges cannot be exported.', '開始点は終了点より前にしてください。長さがゼロの範囲や逆順の範囲は書き出せません。'),
    '速度指数': ('Speed index', '速度指数'),
    '英语转写准确度': ('English transcription accuracy', '英語の文字起こし精度'),
    '数据集': ('Dataset', 'データセット'),
    '指标': ('Metric', '指標'),
    '数值': ('Value', '値'),
    '提前 100 ms': ('100 ms earlier', '100 ms早める'),
    '提前 50 ms': ('50 ms earlier', '50 ms早める'),
    '延后 50 ms': ('50 ms later', '50 ms遅らせる'),
    '延后 100 ms': ('100 ms later', '100 ms遅らせる'),
    '已自动保存 · {time}': ('Autosaved · {time}', '自動保存済み · {time}'),
    '复核 {percent}%': ('Reviewed {percent}%', '確認済み {percent}%'),
})

# Background notifications and generated-panel headings
STRINGS.update({
    '已将 {value0} 条建议加入《{value1}》词库。': ('Suggestions added to “{value1}”: {value0}.', '「{value1}」用語集に候補を{value0}件追加しました。'),
    '已忽略 {value0} 条建议。': ('Suggestions ignored: {value0}.', '候補を{value0}件無視しました。'),
    '「{value0}」更新失败：{value1}': ('Update failed for “{value0}”: {value1}', '「{value0}」の更新に失敗しました：{value1}'),
    '「{value0}」{value1}已提交。切到其它词库也能在任务栏看到进度。': ('“{value0}” — {value1} submitted. Track progress in the task bar while browsing other libraries.', '「{value0}」の{value1}を開始しました。他の用語集に移動してもタスク欄で進捗を確認できます。'),
    '已确认 {value0} 条参考词条。': ('Reference entries confirmed: {value0}.', '参考用語を{value0}件確定しました。'),
    '添加术语失败：该术语已存在或内容为空。': ('Could not add term: it is empty or already exists.', '用語を追加できません。空欄または登録済みです。'),
    '已从检查点继续「{value0}」完整建库。': ('Resumed the full library build for “{value0}” from its checkpoint.', 'チェックポイントから「{value0}」の用語集全体の作成を再開しました。'),
    '「{value0}」已有同模式任务在队列/运行中。': ('A task of the same type for “{value0}” is already queued or running.', '「{value0}」には同じ種類のタスクが待機中または実行中です。'),
    '「{value0}」{value1}完成：新增候选 {value2} · 别名补充 {value3}。': ('“{value0}” — {value1} complete. New candidates: {value2} · Added aliases: {value3}.', '「{value0}」の{value1}が完了しました。新しい候補：{value2}件 · 別名追加：{value3}件。'),
    '「{value0}」{value1}完成：新增候选 {value2} · 别名补充 {value3}（在任务栏点「查看」审阅）。': ('“{value0}” — {value1} complete. New candidates: {value2} · Added aliases: {value3}. Select View in the task bar to review.', '「{value0}」の{value1}が完了しました。新しい候補：{value2}件 · 別名追加：{value3}件。タスク欄の「表示」から確認できます。'),
    '「{value0}」更新已取消（已完成批次保留在检查点）。': ('Update cancelled for “{value0}”. Completed batches are saved in the checkpoint.', '「{value0}」の更新をキャンセルしました。完了済みバッチはチェックポイントに保存されています。'),
    '已应用 {value0} 条更新{value1}{value2}{value3}。': ('Updates applied: {value0}{value1}{value2}{value3}.', '更新を{value0}件適用しました{value1}{value2}{value3}。'),
    '已确认「{value0}」。': ('Confirmed “{value0}”.', '「{value0}」を確定しました。'),
    '已恢复「{value0}」。': ('Restored “{value0}”.', '「{value0}」を復元しました。'),
    '{value0}\n{value1}\n\n{value2} · {value3}\n构图：{value4}\n配色：{value5}\n\n动效：\n{value6} → {value7} → {value8}': ('{value0}\n{value1}\n\n{value2} · {value3}\nComposition: {value4}\nColor: {value5}\n\nMotion:\n{value6} → {value7} → {value8}', '{value0}\n{value1}\n\n{value2} · {value3}\n構図：{value4}\n配色：{value5}\n\nアニメーション：\n{value6} → {value7} → {value8}'),
    '{value0}\n{value1}\n\n动效：{value2}': ('{value0}\n{value1}\n\nMotion: {value2}', '{value0}\n{value1}\n\nアニメーション：{value2}'),
    '{value0}\n完整视觉方向\n\n动效：已使用可信 MotionGraph 编译': ('{value0}\nComplete visual direction\n\nMotion: compiled with trusted MotionGraph', '{value0}\nビジュアル全体の方向性\n\nアニメーション：検証済みMotionGraphでコンパイル済み'),
    '当前文本:\n{value0}\n\nPrimary result:\n{value1}\n\nReview result:\n{value2}\n\nGlossary evidence:\n{value3}\n\n建议:\n{value4}': ('Current text:\n{value0}\n\nPrimary result:\n{value1}\n\nReview result:\n{value2}\n\nGlossary evidence:\n{value3}\n\nRecommendation:\n{value4}', '現在のテキスト：\n{value0}\n\n主認識の結果：\n{value1}\n\n確認用認識の結果：\n{value2}\n\n用語集の根拠：\n{value3}\n\n推奨：\n{value4}'),
    '{value0}候选 {value1} · 保留其他方向': ('{value0}: candidate {value1} · Other directions preserved', '{value0}：候補{value1} · 他の方向性は保持'),
    '{value0}；已应用主题保留': ('{value0}; the applied theme is preserved', '{value0}。適用済みテーマは保持されます'),
})
