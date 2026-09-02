// qml/UpperPane.qml
import QtQuick 2.15
import QtQuick.Controls 2.15 as QQC
import RinUI as Rin

QQC.Pane {
    id: root

    property alias textDocument: textArea.textDocument
    property alias text: textArea.text
    property alias fontSize: textArea.font.pixelSize  // 暴露字体大小属性
    property alias fontFamily: textArea.font.family
    // 跟打时让当前行位于可视区第 3 行（当前行上方预留两行）。
    property int typingLineOffset: 2
    // 退格回滚至少累计两个文字，换行不计入阈值。
    property int backwardScrollThreshold: 2
    property int previousCursorPos: -1
    property int backwardScrollPending: 0
    property real previousTargetY: -1

    function setCursorAndScroll(cursorPos, forceScroll) {
        textArea.setCursorAndScroll(cursorPos, forceScroll);
    }

    // 监听 appBridge 的光标位置变化，同步 UpperPane
    Connections {
        target: appBridge
        function onCursorPosChanged(newPos) {
            textArea.setCursorAndScroll(newPos);
        }
    }

    background: Rectangle {
        color: Rin.Theme.currentTheme ? Rin.Theme.currentTheme.colors.cardColor : "#f5f5f5"
        border.color: Rin.Theme.currentTheme ? Rin.Theme.currentTheme.colors.dividerBorderColor : "#e0e0e0"
        border.width: 1
        radius: 2
    }

    // 面板高度拖动时，主动同步滚动边界并请求文本重绘。
    onHeightChanged: {
        if (!scrollView || !scrollView.contentItem || !textArea)
            return;
        Qt.callLater(function() {
            var maxY = Math.max(0,
                scrollView.contentItem.contentHeight - scrollView.contentItem.height);
            scrollView.contentItem.contentY = Math.min(scrollView.contentItem.contentY, maxY);
            textArea.update();
        });
    }

    QQC.ScrollView {
        id: scrollView
        anchors.fill: parent
        clip: true // 确保文字不超出 Pane 的边界

        // 在 Qt 6 中，ScrollBar 应该附加给 ScrollView
        QQC.ScrollBar.vertical: QQC.ScrollBar {
            policy: QQC.ScrollBar.AsNeeded

            // **位置控制**：通过 anchors 调整
            anchors.right: parent.right          // 贴在右侧
            anchors.rightMargin: 5              // 右边距 5px
            anchors.top: parent.top             // 顶部对齐
            anchors.topMargin: 10               // 顶部边距 10px
            anchors.bottom: parent.bottom       // 底部对齐
            anchors.bottomMargin: 10            // 底部边距 10px

            // **大小控制**
            width: 12                           // 滚动条宽度 12px
            // 高度会自动根据 anchors 计算
        }

        NumberAnimation {
            id: scrollAnimation
            target: scrollView.contentItem
            property: "contentY"
            duration: 180
            easing.type: Easing.OutCubic
        }

        QQC.TextArea {
            id: textArea
            readOnly: true
            wrapMode: QQC.TextArea.Wrap
            textFormat: TextEdit.PlainText   // PlainText 避免 RichText 转换导致 toPlainText() 异常
            font.pixelSize: 14
            text: "你好，世界。"
            color: Rin.Theme.currentTheme ? Rin.Theme.currentTheme.colors.textColor : "black"
            background: Rectangle {
                color: "transparent"
            }

            // 把底层的 textDocument（QQuickTextDocument）传给 Python 的 appBridge
            // 注意：不在这里调 handleLoadedText，等文本加载完成后再由 applyLoadedText 调用
            // 避免用户在 text_id 尚未设置时就开始打字

            function setCursorAndScroll(cursorPos, forceScroll) {
                if (cursorPos < 0 || cursorPos > textArea.length) {
                    return;
                }
                var targetPos = Math.min(cursorPos, Math.max(0, textArea.length - 1));
                textArea.cursorPosition = targetPos;

                Qt.callLater(function() {
                    textArea.scrollToPosition(targetPos, forceScroll === true);
                });
            }

            function scrollToPosition(cursorPos, forceScroll) {
                // 以当前行的顶部为基准定位，避免长文时光标行一直居中。
                var rect = textArea.positionToRectangle(cursorPos);
                if (!rect)
                    return;

                var currentY = scrollView.contentItem.contentY;
                var lineHeight = Math.max(rect.height, textArea.font.pixelSize);
                var targetY = rect.y - lineHeight * root.typingLineOffset;
                var maxY = Math.max(0,
                    scrollView.contentItem.contentHeight - scrollView.contentItem.height);
                targetY = Math.max(0, Math.min(targetY, maxY));

                var movingBackward = targetY < currentY - 0.5;
                if (forceScroll === true || root.previousCursorPos < 0) {
                    root.backwardScrollPending = 0;
                } else if (cursorPos < root.previousCursorPos) {
                    // 跨到上一行的第一次退格只进入上一行，不占用两个字的缓冲。
                    var enteredPreviousLine = targetY < root.previousTargetY - 0.5;
                    if (enteredPreviousLine) {
                        root.backwardScrollPending = 0;
                    } else {
                        var deletedText = textArea.text.substring(cursorPos, root.previousCursorPos);
                        root.backwardScrollPending += deletedText.replace(/[\r\n]/g, "").length;
                    }
                } else {
                    root.backwardScrollPending = 0;
                }
                root.previousCursorPos = cursorPos;
                root.previousTargetY = targetY;

                if (movingBackward &&
                        root.backwardScrollPending < root.backwardScrollThreshold) {
                    return;
                }

                if (forceScroll === true || Math.abs(currentY - targetY) > 0.5) {
                    if (scrollAnimation.running && Math.abs(scrollAnimation.to - targetY) <= 0.5)
                        return;
                    scrollAnimation.stop();
                    scrollAnimation.from = currentY;
                    scrollAnimation.to = targetY;
                    scrollAnimation.start();
                    if (movingBackward)
                        root.backwardScrollPending = 0;
                }
            }
        }
    }
}
