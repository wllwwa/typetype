import QtQuick 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15
import RinUI

/**
 * 52dazi 今日竞赛赛文入口。
 *
 * 比赛类型由面板直接选择，不跟随设置页中的默认比赛类型；后端接口会
 * 根据 competitionType 返回对应的今日赛文。
 */
Frame {
    id: root

    signal loadRequested(int competitionType)

    ListModel {
        id: competitionModel
        ListElement { title: "极速杯"; codeValue: 0; description: "今日极速杯赛文" }
        ListElement { title: "锦标赛"; codeValue: 2; description: "今日锦标赛赛文" }
        ListElement { title: "键神杯"; codeValue: 4; description: "今日键神杯赛文" }
    }

    function openSettings() {
        if (Window.window && Window.window.navigationView)
            Window.window.navigationView.push(Qt.resolvedUrl("../pages/SettingsPage.qml"))
    }

    Layout.fillWidth: true
    Layout.fillHeight: true
    radius: 6
    hoverable: false

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 32, 620)
        spacing: 12

        IconWidget {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 36
            Layout.preferredHeight: 36
            icon: "ic_fluent_trophy_20_regular"
            color: Theme.currentTheme.colors.primaryColor
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            typography: Typography.Subtitle
            color: Theme.currentTheme.colors.textColor
            text: qsTr("52dazi 今日竞赛")
        }

        Text {
            Layout.fillWidth: true
            typography: Typography.Caption
            color: Theme.currentTheme.colors.textSecondaryColor
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            text: qsTr("选择比赛类型，载入今天的竞赛赛文。完成全文赛文后可在跟打页显式上传成绩。")
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                Layout.fillWidth: true
                typography: Typography.Body
                color: Theme.currentTheme.colors.textColor
                text: appBridge && appBridge.daziLoggedIn
                      ? qsTr("已登录：%1").arg(appBridge.daziCurrentUser)
                      : qsTr("未登录 52dazi")
                elide: Text.ElideRight
            }

            Button {
                text: appBridge && appBridge.daziLoggedIn ? qsTr("账号设置") : qsTr("去登录")
                flat: true
                icon.name: "ic_fluent_settings_20_regular"
                onClicked: root.openSettings()
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 8

            Repeater {
                model: competitionModel

                delegate: Frame {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 58
                    radius: 6
                    hoverable: false
                    padding: 8

                    RowLayout {
                        anchors.fill: parent
                        spacing: 10

                        IconWidget {
                            Layout.preferredWidth: 22
                            Layout.preferredHeight: 22
                            icon: "ic_fluent_trophy_20_regular"
                            color: Theme.currentTheme.colors.primaryColor
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2

                            Text {
                                Layout.fillWidth: true
                                typography: Typography.BodyStrong
                                color: Theme.currentTheme.colors.textColor
                                text: model.title
                                elide: Text.ElideRight
                            }

                            Text {
                                Layout.fillWidth: true
                                typography: Typography.Caption
                                color: Theme.currentTheme.colors.textSecondaryColor
                                text: model.description
                                elide: Text.ElideRight
                            }
                        }

                        Button {
                            Layout.preferredWidth: 132
                            Layout.preferredHeight: 36
                            text: qsTr("载入今日赛文")
                            highlighted: true
                            enabled: appBridge && appBridge.daziLoggedIn && !appBridge.daziLoading
                            icon.name: "ic_fluent_document_arrow_down_20_regular"
                            onClicked: root.loadRequested(model.codeValue)
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            BusyIndicator {
                Layout.preferredWidth: 18
                Layout.preferredHeight: 18
                running: appBridge ? appBridge.daziLoading : false
                visible: running
            }

            Text {
                Layout.fillWidth: true
                typography: Typography.Caption
                color: Theme.currentTheme.colors.textSecondaryColor
                text: appBridge && appBridge.daziLoading
                      ? qsTr("正在载入今日竞赛赛文...")
                      : qsTr("需要先登录 52dazi 才能载入竞赛赛文")
                visible: appBridge && appBridge.daziLoading
                       || !(appBridge && appBridge.daziLoggedIn)
            }
        }
    }
}
