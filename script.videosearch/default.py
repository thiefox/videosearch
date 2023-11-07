import sys
from urllib.parse import unquote_plus
import xbmc
import xbmcaddon

LANGUAGE = xbmcaddon.Addon().getLocalizedString
CWD = xbmcaddon.Addon().getAddonInfo('path')

if (__name__ == '__main__'):
    try:
        params = dict(arg.split('=') for arg in sys.argv[1].split('&'))
    except:
        params = {}
    searchstring = unquote_plus(params.get('searchstring',''))
    if searchstring:        #外部给出了查询串
        del params['searchstring']      #删除字典里的查询串KEY？
    else:
        #LANGUAGE(32101)="Enter search string"
        keyboard = xbmc.Keyboard('', LANGUAGE(32101), False)        #系统内置的键盘输入对话框模板？
        keyboard.doModal()      #打开键盘对话框
        if (keyboard.isConfirmed()):    #按了确认键
            searchstring = keyboard.getText()       #获取键盘对话框的输入作为查询串
    if searchstring:        #查询串有效
        from lib import gui
        #这个script-globalsearch.xml是内部的UI管理器吗？
        #然后把查询串作为输入？
        #default/1080i/指明了二级路径
        ui = gui.GUI('script-videosearch.xml', CWD, 'default', '1080i', True, searchstring=searchstring, params=params)
        #打开查询结果对话框
        ui.doModal()
        del ui
