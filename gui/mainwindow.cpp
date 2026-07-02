#include "mainwindow.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QProcess>
#include <QJsonDocument>
#include <QMessageBox>
#include <QApplication>
#include <QGroupBox>
#include <QButtonGroup>
#include <QRadioButton>
#include <QScrollBar>
#include <QDir>
#include <QDebug>

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent)
{
    setWindowTitle("Inra - System Cleaner");
    resize(1100, 700);
    
    currentCategory = "strict_orphans";
    pmBackend = "Unknown";
    cacheSize = "Unknown";
    journalSize = "Unknown";

    initUI();
    applyTheme();
    refreshData();
    sidebarList->setCurrentRow(0);
}

MainWindow::~MainWindow() {}

void MainWindow::initUI() {
    QWidget *centralWidget = new QWidget(this);
    setCentralWidget(centralWidget);

    QHBoxLayout *mainLayout = new QHBoxLayout(centralWidget);
    mainLayout->setContentsMargins(0, 0, 0, 0);
    mainLayout->setSpacing(0);

    // 1. Sidebar Container
    QWidget *sidebarContainer = new QWidget(centralWidget);
    sidebarContainer->setObjectName("sidebarContainer");
    sidebarContainer->setFixedWidth(260);
    
    QVBoxLayout *sidebarLayout = new QVBoxLayout(sidebarContainer);
    sidebarLayout->setContentsMargins(15, 20, 15, 20);
    sidebarLayout->setSpacing(15);

    // Sidebar Title
    QLabel *logoLabel = new QLabel(sidebarContainer);
    logoLabel->setText("INRA SYSTEM CLEANER");
    logoLabel->setObjectName("logoLabel");
    logoLabel->setAlignment(Qt::AlignCenter);
    sidebarLayout->addWidget(logoLabel);

    // Sidebar Categories
    sidebarList = new QListWidget(sidebarContainer);
    sidebarList->setObjectName("sidebarList");
    
    struct SidebarItem {
        QString text;
        QString key;
    };
    
    QVector<SidebarItem> items = {
        {"Strict Orphans", "strict_orphans"},
        {"Optional Orphans", "optional_orphans"},
        {"GUI Applications", "explicit_gui"},
        {"Development Tools", "explicit_dev"},
        {"Fonts & Themes", "explicit_fonts_themes"},
        {"CLI & Other Tools", "explicit_cli_other"},
        {"System Utilities", "utilities"}
    };

    for (const auto &item : items) {
        QListWidgetItem *listItem = new QListWidgetItem(item.text, sidebarList);
        listItem->setData(Qt::UserRole, item.key);
    }
    
    sidebarLayout->addWidget(sidebarList);

    // Sidebar Info Footer
    QFrame *sidebarFooter = new QFrame(sidebarContainer);
    sidebarFooter->setFrameShape(QFrame::HLine);
    sidebarFooter->setFrameShadow(QFrame::Sunken);
    sidebarLayout->addWidget(sidebarFooter);

    statBackendLabel = new QLabel("Backend: Scanning...", sidebarContainer);
    statBackendLabel->setObjectName("statBackendLabel");
    sidebarLayout->addWidget(statBackendLabel);

    mainLayout->addWidget(sidebarContainer);

    // 2. Main content area
    QWidget *contentArea = new QWidget(centralWidget);
    contentArea->setObjectName("contentArea");
    
    QVBoxLayout *contentLayout = new QVBoxLayout(contentArea);
    contentLayout->setContentsMargins(25, 25, 25, 25);
    contentLayout->setSpacing(20);

    // Top Stats Dashboard Header
    QWidget *statsHeader = new QWidget(contentArea);
    statsHeader->setObjectName("statsHeader");
    QHBoxLayout *statsHeaderLayout = new QHBoxLayout(statsHeader);
    statsHeaderLayout->setContentsMargins(0, 0, 0, 0);
    statsHeaderLayout->setSpacing(20);

    // Card 1: Candidates
    QWidget *card1 = new QWidget(statsHeader);
    card1->setObjectName("statCard");
    QVBoxLayout *card1Layout = new QVBoxLayout(card1);
    QLabel *card1Title = new QLabel("CANDIDATES", card1);
    card1Title->setObjectName("cardTitle");
    statCountLabel = new QLabel("0", card1);
    statCountLabel->setObjectName("cardValueCyan");
    card1Layout->addWidget(card1Title);
    card1Layout->addWidget(statCountLabel);
    statsHeaderLayout->addWidget(card1);

    // Card 2: Reclaimable
    QWidget *card2 = new QWidget(statsHeader);
    card2->setObjectName("statCard");
    QVBoxLayout *card2Layout = new QVBoxLayout(card2);
    QLabel *card2Title = new QLabel("RECLAIMABLE SPACE", card2);
    card2Title->setObjectName("cardTitle");
    statSizeLabel = new QLabel("0 B", card2);
    statSizeLabel->setObjectName("cardValueGreen");
    card2Layout->addWidget(card2Title);
    card2Layout->addWidget(statSizeLabel);
    statsHeaderLayout->addWidget(card2);

    contentLayout->addWidget(statsHeader);

    // Packages List View container (Search + Table)
    QWidget *packagesPanel = new QWidget(contentArea);
    QVBoxLayout *packagesPanelLayout = new QVBoxLayout(packagesPanel);
    packagesPanelLayout->setContentsMargins(0, 0, 0, 0);
    packagesPanelLayout->setSpacing(15);

    // Search Line Edit
    searchEdit = new QLineEdit(packagesPanel);
    searchEdit->setPlaceholderText("Search package by name or description...");
    searchEdit->setObjectName("searchEdit");
    packagesPanelLayout->addWidget(searchEdit);

    // Table
    packageTable = new QTableWidget(packagesPanel);
    packageTable->setColumnCount(6);
    packageTable->setHorizontalHeaderLabels({"[ ]", "Package Name", "Version", "Installed Size", "Recursive Size", "Description"});
    packageTable->verticalHeader()->setVisible(false);
    packageTable->setSelectionBehavior(QAbstractItemView::SelectRows);
    packageTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
    packageTable->setObjectName("packageTable");
    
    QHeaderView *header = packageTable->horizontalHeader();
    header->setSectionResizeMode(0, QHeaderView::Fixed);
    packageTable->setColumnWidth(0, 45);
    header->setSectionResizeMode(1, QHeaderView::Interactive);
    packageTable->setColumnWidth(1, 160);
    header->setSectionResizeMode(2, QHeaderView::Interactive);
    packageTable->setColumnWidth(2, 100);
    header->setSectionResizeMode(3, QHeaderView::Interactive);
    packageTable->setColumnWidth(3, 110);
    header->setSectionResizeMode(4, QHeaderView::Interactive);
    packageTable->setColumnWidth(4, 120);
    header->setSectionResizeMode(5, QHeaderView::Stretch);

    packagesPanelLayout->addWidget(packageTable);
    contentLayout->addWidget(packagesPanel);

    // Utilities Panel (hidden by default)
    utilitiesPanel = new QWidget(contentArea);
    utilitiesPanel->setVisible(false);
    QVBoxLayout *utilitiesLayout = new QVBoxLayout(utilitiesPanel);
    utilitiesLayout->setContentsMargins(0, 0, 0, 0);
    utilitiesLayout->setSpacing(25);

    // Cache clean box
    QGroupBox *cacheBox = new QGroupBox("Package Manager Cache Cleanup", utilitiesPanel);
    cacheBox->setObjectName("utilitiesGroup");
    QVBoxLayout *cacheBoxLayout = new QVBoxLayout(cacheBox);
    cacheBoxLayout->setContentsMargins(20, 20, 20, 20);
    cacheBoxLayout->setSpacing(15);
    
    QHBoxLayout *cacheSub = new QHBoxLayout();
    QLabel *cSizeTitle = new QLabel("Current Cache Size: ", cacheBox);
    cacheSizeLabel = new QLabel("Scanning...", cacheBox);
    cacheSizeLabel->setStyleSheet("color: #00e676; font-weight: bold;");
    cacheSub->addWidget(cSizeTitle);
    cacheSub->addWidget(cacheSizeLabel);
    cacheSub->addStretch();
    cacheBoxLayout->addLayout(cacheSub);

    QButtonGroup *cacheGroup = new QButtonGroup(cacheBox);
    cacheMode1 = new QCheckBox("Remove uninstalled packages' cached archives (Recommended)", cacheBox);
    cacheMode2 = new QCheckBox("Clear entire package manager cache (All downloaded archives)", cacheBox);
    cacheMode1->setChecked(true);
    cacheGroup->addButton(cacheMode1);
    cacheGroup->addButton(cacheMode2);
    cacheBoxLayout->addWidget(cacheMode1);
    cacheBoxLayout->addWidget(cacheMode2);

    cleanCacheBtn = new QPushButton("Clean Package Cache", cacheBox);
    cleanCacheBtn->setObjectName("actionBtnGreen");
    cacheBoxLayout->addWidget(cleanCacheBtn);
    utilitiesLayout->addWidget(cacheBox);

    // Journal vacuum box
    QGroupBox *journalBox = new QGroupBox("Systemd Journal Vacuum", utilitiesPanel);
    journalBox->setObjectName("utilitiesGroup");
    QVBoxLayout *journalBoxLayout = new QVBoxLayout(journalBox);
    journalBoxLayout->setContentsMargins(20, 20, 20, 20);
    journalBoxLayout->setSpacing(15);

    QHBoxLayout *journalSub = new QHBoxLayout();
    QLabel *jSizeTitle = new QLabel("Current Journal Size: ", journalBox);
    journalSizeLabel = new QLabel("Scanning...", journalBox);
    journalSizeLabel->setStyleSheet("color: #00e676; font-weight: bold;");
    journalSub->addWidget(jSizeTitle);
    journalSub->addWidget(journalSizeLabel);
    journalSub->addStretch();
    journalBoxLayout->addLayout(journalSub);

    QButtonGroup *journalGroup = new QButtonGroup(journalBox);
    journalMode1 = new QCheckBox("Vacuum logs older than 2 days", journalBox);
    journalMode2 = new QCheckBox("Vacuum logs older than 7 days", journalBox);
    journalMode3 = new QCheckBox("Vacuum logs to fit under 100 MB", journalBox);
    journalMode4 = new QCheckBox("Vacuum logs to fit under 500 MB", journalBox);
    journalMode1->setChecked(true);
    journalGroup->addButton(journalMode1);
    journalGroup->addButton(journalMode2);
    journalGroup->addButton(journalMode3);
    journalGroup->addButton(journalMode4);

    journalBoxLayout->addWidget(journalMode1);
    journalBoxLayout->addWidget(journalMode2);
    journalBoxLayout->addWidget(journalMode3);
    journalBoxLayout->addWidget(journalMode4);

    vacuumJournalBtn = new QPushButton("Vacuum Journal Logs", journalBox);
    vacuumJournalBtn->setObjectName("actionBtnGreen");
    journalBoxLayout->addWidget(vacuumJournalBtn);
    utilitiesLayout->addWidget(journalBox);

    utilitiesLayout->addStretch();
    contentLayout->addWidget(utilitiesPanel);

    // Floating action bar at bottom
    actionBar = new QWidget(contentArea);
    actionBar->setObjectName("actionBar");
    actionBar->setFixedHeight(65);
    actionBar->setVisible(false);
    
    QHBoxLayout *actionBarLayout = new QHBoxLayout(actionBar);
    actionBarLayout->setContentsMargins(20, 0, 20, 0);
    
    actionBarLabel = new QLabel("Selected: 0 packages (Reclaiming 0 B)", actionBar);
    actionBarLabel->setObjectName("actionBarLabel");
    actionBarLayout->addWidget(actionBarLabel);
    actionBarLayout->addStretch();
    
    purgeButton = new QPushButton("PURGE SELECTED", actionBar);
    purgeButton->setObjectName("actionBtnRed");
    actionBarLayout->addWidget(purgeButton);
    
    contentLayout->addWidget(actionBar);

    mainLayout->addWidget(contentArea);

    // Connect signals and slots
    connect(sidebarList, &QListWidget::itemSelectionChanged, this, &MainWindow::onSidebarSelectionChanged);
    connect(searchEdit, &QLineEdit::textChanged, this, &MainWindow::onSearchTextChanged);
    connect(purgeButton, &QPushButton::clicked, this, &MainWindow::onPurgeButtonClicked);
    connect(cleanCacheBtn, &QPushButton::clicked, this, &MainWindow::onCacheCleanClicked);
    connect(vacuumJournalBtn, &QPushButton::clicked, this, &MainWindow::onJournalVacuumClicked);
    connect(packageTable->horizontalHeader(), &QHeaderView::sectionClicked, this, &MainWindow::onTableSortChanged);
}

void MainWindow::applyTheme() {
    QString qss = R"(
        QMainWindow {
            background-color: #080b11;
        }
        #sidebarContainer {
            background-color: #0b0f1a;
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }
        #contentArea {
            background-color: #080b11;
        }
        #logoLabel {
            color: #00d2ff;
            font-size: 14px;
            font-weight: bold;
            letter-spacing: 2px;
            padding: 10px 0px;
        }
        #sidebarList {
            background-color: transparent;
            border: none;
            outline: none;
        }
        #sidebarList::item {
            color: #94a3b8;
            padding: 12px 15px;
            border-radius: 8px;
            font-weight: 500;
            font-size: 13px;
            margin-bottom: 5px;
        }
        #sidebarList::item:hover {
            background-color: rgba(255, 255, 255, 0.04);
            color: #f1f5f9;
        }
        #sidebarList::item:selected {
            background-color: rgba(0, 210, 255, 0.12);
            color: #00d2ff;
            border-left: 3px solid #00d2ff;
        }
        #statBackendLabel {
            color: #94a3b8;
            font-size: 11px;
            font-weight: bold;
            padding: 5px;
        }
        #statCard {
            background-color: rgba(18, 26, 41, 0.55);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 12px;
            padding: 12px 18px;
        }
        #cardTitle {
            color: #94a3b8;
            font-size: 10px;
            font-weight: bold;
            letter-spacing: 1px;
        }
        #cardValueCyan {
            color: #00d2ff;
            font-size: 24px;
            font-weight: bold;
            margin-top: 4px;
        }
        #cardValueGreen {
            color: #00e676;
            font-size: 24px;
            font-weight: bold;
            margin-top: 4px;
        }
        #searchEdit {
            background-color: rgba(18, 26, 41, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            color: #f1f5f9;
            padding: 10px 15px;
            font-size: 13px;
        }
        #searchEdit:focus {
            border: 1px solid #00d2ff;
            background-color: rgba(18, 26, 41, 0.7);
        }
        #packageTable {
            background-color: rgba(18, 26, 41, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 10px;
            gridline-color: rgba(255, 255, 255, 0.04);
            color: #e2e8f0;
            font-size: 12px;
        }
        #packageTable QHeaderView::section {
            background-color: #0b0f1a;
            color: #94a3b8;
            padding: 8px;
            border: none;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            font-weight: bold;
            font-size: 11px;
        }
        #packageTable QScrollBar:vertical {
            border: none;
            background: #080b11;
            width: 8px;
            margin: 0px;
        }
        #packageTable QScrollBar::handle:vertical {
            background: rgba(255, 255, 255, 0.15);
            min-height: 20px;
            border-radius: 4px;
        }
        #packageTable QScrollBar::handle:vertical:hover {
            background: rgba(0, 210, 255, 0.4);
        }
        #actionBar {
            background-color: rgba(18, 26, 41, 0.95);
            border: 1px solid #00d2ff;
            border-radius: 10px;
        }
        #actionBarLabel {
            color: #f1f5f9;
            font-weight: 500;
            font-size: 13px;
        }
        #actionBtnGreen {
            background-color: #00e676;
            color: #080b11;
            border: none;
            border-radius: 6px;
            padding: 8px 15px;
            font-weight: bold;
            font-size: 12px;
        }
        #actionBtnGreen:hover {
            background-color: #00c853;
        }
        #actionBtnRed {
            background-color: #ff1744;
            color: #f1f5f9;
            border: none;
            border-radius: 6px;
            padding: 10px 20px;
            font-weight: bold;
            font-size: 12px;
        }
        #actionBtnRed:hover {
            background-color: #d50000;
        }
        #utilitiesGroup {
            color: #f1f5f9;
            font-weight: bold;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 15px;
        }
        #utilitiesGroup QCheckBox {
            color: #cbd5e1;
            font-size: 12px;
        }
    )";
    setStyleSheet(qss);
}

QString MainWindow::findInraBackend() {
    // Try current workspace directory
    QString curDir = QDir::currentPath();
    if (QFile::exists(curDir + "/inra.py")) {
        return "python3 " + curDir + "/inra.py";
    }
    
    // Try parent directory
    if (QFile::exists(curDir + "/../inra.py")) {
        return "python3 " + curDir + "/../inra.py";
    }

    // Try /usr/bin/inra.py or /usr/bin/inra
    if (QFile::exists("/usr/bin/inra.py")) {
        return "python3 /usr/bin/inra.py";
    }
    if (QFile::exists("/usr/bin/inra")) {
        // Since /usr/bin/inra is python or symlink
        return "/usr/bin/inra";
    }

    // Default fallback
    return "inra";
}

void MainWindow::refreshData() {
    selectedPackages.clear();
    categoriesData.clear();

    QString cmdStr = findInraBackend();
    QStringList args;
    QString runCmd;
    if (cmdStr.startsWith("python3 ")) {
        runCmd = "python3";
        args << cmdStr.mid(8) << "--json";
    } else {
        runCmd = cmdStr;
        args << "--json";
    }

    QProcess process;
    process.start(runCmd, args);
    if (!process.waitForFinished(10000)) {
        QMessageBox::critical(this, "Scan Failed", "Package scanner timed out or failed to execute: " + cmdStr);
        return;
    }

    QByteArray output = process.readAllStandardOutput();
    QJsonDocument doc = QJsonDocument::fromJson(output);
    if (doc.isNull() || !doc.isObject()) {
        QString errStr = process.readAllStandardError();
        QMessageBox::critical(this, "Parser Error", "Failed to parse system scan JSON. Output was:\n" + QString(output) + "\n\nError output:\n" + errStr);
        return;
    }

    QJsonObject rootObj = doc.object();
    
    // If the python script returned an error inside JSON
    if (rootObj.contains("error")) {
        QMessageBox::critical(this, "Backend Error", rootObj.value("error").toString());
        return;
    }

    // Parse categories
    pmBackend = rootObj.value("package_manager").toString("Unknown");
    cacheSize = rootObj.value("cache_size").toString("Unknown");
    journalSize = rootObj.value("journal_size").toString("Unknown");
    
    statBackendLabel->setText("Backend: " + pmBackend);
    cacheSizeLabel->setText(cacheSize);
    journalSizeLabel->setText(journalSize);

    QJsonObject cats = rootObj.value("categories").toObject();
    
    qint64 grandTotalCount = 0;
    qint64 grandTotalBytes = 0;

    for (auto it = cats.begin(); it != cats.end(); ++it) {
        QString catName = it.key();
        QJsonArray pkgsArr = it.value().toArray();
        QVector<InraPackage> list;
        
        for (const QJsonValue &val : pkgsArr) {
            QJsonObject obj = val.toObject();
            InraPackage p;
            p.name = obj.value("name").toString();
            p.version = obj.value("version").toString();
            p.description = obj.value("description").toString();
            p.installedSize = obj.value("installed_size").toDouble();
            p.recursiveSize = obj.value("recursive_size").toDouble();
            p.installDate = obj.value("install_date").toDouble();
            p.url = obj.value("url").toString();
            
            QJsonArray recPkgs = obj.value("recursive_packages").toArray();
            for (const QJsonValue &rVal : recPkgs) {
                p.recursivePackages.append(rVal.toString());
            }

            list.append(p);
            grandTotalCount++;
            grandTotalBytes += p.installedSize;
        }
        
        categoriesData[catName] = list;
    }

    statCountLabel->setText(QString::number(grandTotalCount));
    statSizeLabel->setText(formatSize(grandTotalBytes));

    // Update list widget counts
    for (int i = 0; i < sidebarList->count(); ++i) {
        QListWidgetItem *item = sidebarList->item(i);
        QString key = item->data(Qt::UserRole).toString();
        if (key != "utilities") {
            int count = categoriesData.value(key).size();
            item->setText(item->text().split(" (").first() + " (" + QString::number(count) + ")");
        }
    }

    renderPackageTable();
    updateActionBar();
}

void MainWindow::onSidebarSelectionChanged() {
    QListWidgetItem *item = sidebarList->currentItem();
    if (!item) return;

    currentCategory = item->data(Qt::UserRole).toString();
    
    if (currentCategory == "utilities") {
        packageTable->parentWidget()->setVisible(false);
        utilitiesPanel->setVisible(true);
    } else {
        packageTable->parentWidget()->setVisible(true);
        utilitiesPanel->setVisible(false);
        renderPackageTable();
    }
}

void MainWindow::onSearchTextChanged(const QString &text) {
    Q_UNUSED(text);
    renderPackageTable();
}

void MainWindow::onTableSortChanged(int logicalIndex) {
    // Sort logic handled natively or we just let it sort
    Q_UNUSED(logicalIndex);
}

void MainWindow::renderPackageTable() {
    packageTable->setRowCount(0);
    
    QString searchVal = searchEdit->text().trimmed().toLower();
    QVector<InraPackage> pkgs = categoriesData.value(currentCategory);
    
    int row = 0;
    for (const auto &pkg : pkgs) {
        if (!searchVal.isEmpty()) {
            if (!pkg.name.toLower().contains(searchVal) && !pkg.description.toLower().contains(searchVal)) {
                continue;
            }
        }

        packageTable->insertRow(row);
        
        // Col 0: Checkbox
        QCheckBox *cb = new QCheckBox(packageTable);
        cb->setChecked(selectedPackages.value(pkg.name, false));
        cb->setProperty("pkgName", pkg.name);
        connect(cb, &QCheckBox::stateChanged, this, &MainWindow::onPackageCheckStateChanged);
        
        QWidget *cbWidget = new QWidget(packageTable);
        QHBoxLayout *cbLayout = new QHBoxLayout(cbWidget);
        cbLayout->addWidget(cb);
        cbLayout->setAlignment(Qt::AlignCenter);
        cbLayout->setContentsMargins(0, 0, 0, 0);
        packageTable->setCellWidget(row, 0, cbWidget);

        // Col 1: Name
        QTableWidgetItem *nameItem = new QTableWidgetItem(pkg.name);
        nameItem->setForeground(QColor("#ffffff"));
        nameItem->setFont(QFont("", 10, QFont::Bold));
        packageTable->setItem(row, 1, nameItem);

        // Col 2: Version
        packageTable->setItem(row, 2, new QTableWidgetItem(pkg.version));

        // Col 3: Size
        packageTable->setItem(row, 3, new QTableWidgetItem(formatSize(pkg.installedSize)));

        // Col 4: Rec Size
        QTableWidgetItem *recSizeItem = new QTableWidgetItem(formatSize(pkg.recursiveSize));
        recSizeItem->setForeground(QColor("#00d2ff"));
        recSizeItem->setFont(QFont("", 10, QFont::Bold));
        packageTable->setItem(row, 4, recSizeItem);

        // Col 5: Description
        QTableWidgetItem *descItem = new QTableWidgetItem(pkg.description);
        descItem->setToolTip(pkg.description);
        packageTable->setItem(row, 5, descItem);

        row++;
    }
}

void MainWindow::onPackageCheckStateChanged(int state) {
    QCheckBox *cb = qobject_cast<QCheckBox*>(sender());
    if (!cb) return;

    QString pkgName = cb->property("pkgName").toString();
    selectedPackages[pkgName] = (state == Qt::Checked);
    if (!selectedPackages[pkgName]) {
        selectedPackages.remove(pkgName);
    }
    updateActionBar();
}

void MainWindow::updateActionBar() {
    int count = 0;
    qint64 totalBytes = 0;
    
    QVector<InraPackage> pkgs = categoriesData.value(currentCategory);
    for (const auto &pkg : pkgs) {
        if (selectedPackages.value(pkg.name, false)) {
            count++;
            totalBytes += pkg.recursiveSize;
        }
    }

    if (count == 0) {
        actionBar->setVisible(false);
    } else {
        actionBar->setVisible(true);
        actionBarLabel->setText(QString("Selected: %1 packages (Reclaiming %2)")
                               .arg(count)
                               .arg(formatSize(totalBytes)));
    }
}

void MainWindow::onPurgeButtonClicked() {
    QStringList pkgsToPurge;
    for (auto it = selectedPackages.begin(); it != selectedPackages.end(); ++it) {
        if (it.value()) {
            pkgsToPurge << it.key();
        }
    }

    if (pkgsToPurge.isEmpty()) return;

    QString confirmMsg = QString("Are you sure you want to purge the following %1 packages and all their recursive orphans?\n\n%2")
                         .arg(pkgsToPurge.size())
                         .arg(pkgsToPurge.join(", "));
                         
    if (QMessageBox::question(this, "Confirm Purge", confirmMsg) != QMessageBox::Yes) {
        return;
    }

    QStringList args;
    args << "--purge" << pkgsToPurge;
    
    startProcessWithOutput(args);
}

void MainWindow::onCacheCleanClicked() {
    QString mode = cacheMode1->isChecked() ? "1" : "2";
    
    QString confirmMsg = mode == "1" 
        ? "Are you sure you want to remove uninstalled packages' cached archives?"
        : "Are you sure you want to clear the entire package manager download cache?";
        
    if (QMessageBox::question(this, "Confirm Cache Clean", confirmMsg) != QMessageBox::Yes) {
        return;
    }

    QStringList args;
    args << "--clean-cache" << mode;
    startProcessWithOutput(args);
}

void MainWindow::onJournalVacuumClicked() {
    QString mode = "1";
    if (journalMode2->isChecked()) mode = "2";
    else if (journalMode3->isChecked()) mode = "3";
    else if (journalMode4->isChecked()) mode = "4";

    QString confirmMsg = "Are you sure you want to vacuum the systemd journal logs?";
    if (QMessageBox::question(this, "Confirm Journal Vacuum", confirmMsg) != QMessageBox::Yes) {
        return;
    }

    QStringList args;
    args << "--vacuum-journal" << mode;
    startProcessWithOutput(args);
}

void MainWindow::startProcessWithOutput(const QStringList &args) {
    // We launch a custom dialog with a QTextEdit to print the process stdout in real-time!
    QDialog *dialog = new QDialog(this);
    dialog->setWindowTitle("INRA Execution Log");
    dialog->resize(700, 400);
    dialog->setStyleSheet("background-color: #0b0f1a; color: #f1f5f9; font-family: monospace;");
    
    QVBoxLayout *layout = new QVBoxLayout(dialog);
    QTextEdit *logConsole = new QTextEdit(dialog);
    logConsole->setReadOnly(true);
    logConsole->setObjectName("logConsole");
    logConsole->setStyleSheet("background-color: #05070c; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 6px; padding: 10px; color: #39ff14;");
    layout->addWidget(logConsole);

    QPushButton *closeBtn = new QPushButton("Close", dialog);
    closeBtn->setEnabled(false);
    layout->addWidget(closeBtn);
    
    connect(closeBtn, &QPushButton::clicked, dialog, &QDialog::accept);

    QProcess *process = new QProcess(dialog);
    
    // Connect standard output and error to console log
    connect(process, &QProcess::readyReadStandardOutput, [process, logConsole]() {
        logConsole->append(QString::fromLocal8Bit(process->readAllStandardOutput()));
        logConsole->verticalScrollBar()->setValue(logConsole->verticalScrollBar()->maximum());
    });
    connect(process, &QProcess::readyReadStandardError, [process, logConsole]() {
        logConsole->append("<font color='#ff1744'>" + QString::fromLocal8Bit(process->readAllStandardError()) + "</font>");
        logConsole->verticalScrollBar()->setValue(logConsole->verticalScrollBar()->maximum());
    });

    connect(process, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished), [process, logConsole, closeBtn](int exitCode, QProcess::ExitStatus exitStatus) {
        Q_UNUSED(exitStatus);
        if (exitCode == 0) {
            logConsole->append("\n<font color='#00e676'><b>SUCCESS: Operation completed successfully!</b></font>");
        } else {
            logConsole->append(QString("\n<font color='#ff1744'><b>FAILED: Command finished with exit code %1</b></font>").arg(exitCode));
        }
        closeBtn->setEnabled(true);
        process->deleteLater();
    });

    // Check if we need to run as root using pkexec
    QString cmdStr = findInraBackend();
    QStringList finalArgs;
    
    if (QFile::exists("/usr/bin/pkexec")) {
        finalArgs << "pkexec";
    } else {
        finalArgs << "sudo";
    }

    if (cmdStr.startsWith("python3 ")) {
        finalArgs << "python3" << cmdStr.mid(8);
    } else {
        finalArgs << cmdStr;
    }
    
    finalArgs.append(args);

    logConsole->append("Executing: " + finalArgs.join(" ") + "\n");
    
    process->start(finalArgs.first(), finalArgs.mid(1));
    dialog->exec();

    // After dialog finishes, refresh data
    refreshData();
}

QString MainWindow::formatSize(qint64 bytes) {
    if (bytes == 0) return "0 B";
    if (bytes < 1024) return QString::number(bytes) + " B";
    double dBytes = bytes;
    QStringList units = {"B", "KB", "MB", "GB", "TB"};
    int i = 0;
    while (dBytes >= 1024 && i < units.size() - 1) {
        dBytes /= 1024.0;
        i++;
    }
    return QString::number(dBytes, 'f', 2) + " " + units[i];
}
