#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>
#include <QListWidget>
#include <QTableWidget>
#include <QLineEdit>
#include <QPushButton>
#include <QLabel>
#include <QJsonObject>
#include <QJsonArray>
#include <QMap>
#include <QVector>
#include <QCheckBox>
#include <QDialog>
#include <QTextEdit>

struct InraPackage {
    QString name;
    QString version;
    QString description;
    qint64 installedSize;
    qint64 recursiveSize;
    QStringList recursivePackages;
    qint64 installDate;
    QString url;
};

class MainWindow : public QMainWindow {
    Q_OBJECT

public:
    MainWindow(QWidget *parent = nullptr);
    ~MainWindow();

private slots:
    void onSidebarSelectionChanged();
    void onSearchTextChanged(const QString &text);
    void onPackageCheckStateChanged(int state);
    void onPurgeButtonClicked();
    void onCacheCleanClicked();
    void onJournalVacuumClicked();
    void onTableSortChanged(int logicalIndex);

private:
    void initUI();
    void applyTheme();
    void refreshData();
    void renderPackageTable();
    void updateActionBar();
    QString formatSize(qint64 bytes);
    QString findInraBackend();
    void startProcessWithOutput(const QStringList &args);

    // GUI Elements
    QListWidget *sidebarList;
    QTableWidget *packageTable;
    QLineEdit *searchEdit;
    QLabel *statCountLabel;
    QLabel *statSizeLabel;
    QLabel *statBackendLabel;
    
    // Action bar
    QWidget *actionBar;
    QLabel *actionBarLabel;
    QPushButton *purgeButton;

    // Cache/Journal Elements
    QWidget *utilitiesPanel;
    QCheckBox *cacheMode1;
    QCheckBox *cacheMode2;
    QCheckBox *journalMode1;
    QCheckBox *journalMode2;
    QCheckBox *journalMode3;
    QCheckBox *journalMode4;
    QPushButton *cleanCacheBtn;
    QPushButton *vacuumJournalBtn;

    // Data maps
    QString currentCategory;
    QMap<QString, QVector<InraPackage>> categoriesData;
    QMap<QString, bool> selectedPackages; // pkgName -> selected
    QString pmBackend;
    QString cacheSize;
    QString journalSize;
    
    // Cache sizes labels
    QLabel *cacheSizeLabel;
    QLabel *journalSizeLabel;
};

#endif // MAINWINDOW_H
