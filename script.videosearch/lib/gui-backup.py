import datetime
import json
import operator
from .defs import *

def log(txt):
    message = '%s: %s' % (ADDONID, txt)
    xbmc.log(msg=message, level=xbmc.LOGDEBUG)

#初始化模板是某个.xml文件
#每个从xbmcgui.WindowXML继承的窗口都有一个list数据container
class GUI(xbmcgui.WindowXML):
    def __init__(self, *args, **kwargs):
        self.params = kwargs['params']          #参数
        self.searchstring = kwargs['searchstring']  #查询串

    #控件初始化
    #设置初始化
    #查询数据和加载
    #self._new_search()的最后也会调用这个OnInit
    def onInit(self):
        self.clearList()    #已有list数据清除（存在的话）
        self._hide_controls()
        log('script version %s started' % ADDONVERSION)
        self.nextsearch = False
        self.navback = False
        #翻页历史还是操作历史
        #history字典的key是level, value又是一个字典，字典有两个key, cats和searchstring，value为对应的值。
        self.history = {}       
        self.menuposition = 0
        #搜索字符串标准化
        self.searchstring = self._clean_string(self.searchstring).strip()
        if self.searchstring == '':
            self._close()
        else:
            self.window_id = xbmcgui.getCurrentWindowId()       #自身的WINDOW ID
            #search string作为属性给窗口
            xbmcgui.Window(self.window_id).setProperty('GlobalSearch.SearchString', self.searchstring)
            if not self.nextsearch:     #这个条件是为什么？之前的上下文？
                if self.params == {}:
                    self._load_settings()   #载入默认设置，由系统的addon取得各个category(movie/tvshow...)的enable状态
                else:
                    self._parse_argv()      #从参数载入设置，也是对各个category的enable状态置位
                self._get_preferences()
                self._load_favourites()     #载入收藏夹数据
            self._reset_variables()
            self._init_items()      #成员变量复位
            self.menu.reset()
            self._set_view()        #设置视图模式
            self._fetch_items()
    #把三个主要的控件（搜索BUTTON, 搜索结果分类GROUP，无结果LABEL）都设置为不可见
    def _hide_controls(self):
        for cid in [SEARCHBUTTON, NORESULTS]:
            self.getControl(cid).setVisible(False)
    #从参数获取categories的enable状态
    def _parse_argv(self):
        for key, value in self.params.items():
            CATEGORIES[key]['enabled'] = self.params[key] == 'true'
    #从系统ADDON获取categories的enable状态
    def _load_settings(self):
        for key, value in CATEGORIES.items():
            #albumsongs/artistalbums/...这些的enabled都为FALSE
            if key not in ('albumsongs', 'artistalbums', 'tvshowseasons', 'seasonepisodes', 'actormovies', 'directormovies', 'actortvshows'):
                CATEGORIES[key]['enabled'] = ADDON.getSettingBool(key)
    #用jsonrpc从KODI系统读取playaction（整数值，视频相关）和albumartists（BOOL，音频相关）两个值。
    def _get_preferences(self):
        json_query = xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Settings.GetSettingValue", "params":{"setting":"myvideos.selectaction"}, "id": 1}')
        json_response = json.loads(json_query)
        self.playaction = 1
        if 'result' in json_response and json_response['result'] != None and 'value' in json_response['result']:
            self.playaction = json_response['result']['value']
        json_query = xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Settings.GetSettingValue", "params":{"setting":"musiclibrary.showcompilationartists"}, "id": 1}')
        json_response = json.loads(json_query)
        self.albumartists = "false"
        if 'result' in json_response and json_response['result'] != None and 'value' in json_response['result']:
            if json_response['result']['value'] == "false":
                self.albumartists = "true"
    #用jsonrpc从系统读取收藏夹列表，载入到self.favourites。
    def _load_favourites(self):
        self.favourites = []
        json_query = xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"Favourites.GetFavourites", "params":{"properties":["path", "windowparameter"]}, "id": 1}')
        json_response = json.loads(json_query)
        if 'result' in json_response and json_response['result'] != None and 'favourites' in json_response['result'] and json_response['result']['favourites'] != None:
            for item in json_response['result']['favourites']:
                if 'path' in item:
                    self.favourites.append(item['path'])
                elif 'windowparameter' in item:
                    self.favourites.append(item['windowparameter'])
    #这个self.focusset的BOOL起什么作用？
    #每次调用self.addItems加入items到UI后，focusset会被置位为TRUE
    def _reset_variables(self):
        #这个focusset只有两个字符串值，true和false，那为什么不用BOOL类型？
        self.focusset= 'false'
    #内容清除，状态复位
    def _init_items(self):
        self.Player = MyPlayer()    #创建一个播放器实例
        self.menu = self.getControl(MENU)       #左面板的媒体分类菜单？？？
        self.content = {} 
        #oldfocus只跟菜单状态相关，每次menu.reset()时，oldfocus都会紧接着复位0
        #当在菜单上发生（方向盘）action（上/下/左/右）时，oldfocus会改变。
        self.oldfocus = 0

    #先读取窗口container的ViewMode，后设置。
    def _set_view(self):
        # no view will be loaded unless we call SetViewMode, might be a bug...
        xbmc.executebuiltin('Container.SetViewMode(0)')
        vid = ADDON.getSettingInt('view')
        # kodi bug: need to call Container.SetViewMode twice
        xbmc.executebuiltin('Container.SetViewMode(%i)' % vid)

    #对各个需要的分类媒体进行搜索
    #每次从KODI获取数据前，level都会复位成1.
    #历史记录打点
    #启动新的搜索才会调用这个函数。在页面内部nav哪怕检索数据也不会调用这个函数。
    def _fetch_items(self):
        #level值初始化
        #这个level在_get_allitems函数中累加
        #即每次获取新数据，level复位为1. 然后随着onClick等操作，累加这个level值？
        self.level = 1          
        cats = []   
        for key, value in sorted(CATEGORIES.items(), key=lambda x: x[1]['order']):  #对静态类目二级字典按order排序转置
            if CATEGORIES[key]['enabled']:      #key为movies/tvshows/episodes etc... enabled意思是这个分类需要搜索？
                self._get_items(CATEGORIES[key], self.searchstring)     #内部会调用self.addItems保存搜索结果
                cats.append(CATEGORIES[key])
        self.history[self.level] = {'cats':cats, 'search':self.searchstring}        #self.level的值不变的？
        self._check_focus()

    #获取某个category(cat:movie/tvshow...)的搜索结果
    #用jsonrpc从KODI主程序获取查询结果
    #内部调用self.addItems加入元素
    #addItems是父类windowXML的内置成员函数
    #外部进入新的搜索和内部的nav都会触发_get_items()
    def _get_items(self, cat, search):
        if cat['content'] == 'livetv':      #电视直播？
            self._fetch_channelgroups(cat)
            return
        if cat['type'] == 'seasonepisodes': #剧集
            search = search[0], search[1]
            rule = cat['rule'].format(query0 = search[0], query1 = search[1])
        else:                               #电影或音乐？
            rule = cat['rule'].format(query = search)
        #分类搜索结果
        self.getControl(SEARCHCATEGORY).setLabel(xbmc.getLocalizedString(cat['label']))     #当前cat分类可见，比如”电影“
        self.getControl(SEARCHCATEGORY).setVisible(True)        #整个控件确保visible
        #调用kodi的json rpc来获取电影信息？
        json_query = xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"%s", "params":{"properties":%s, "sort":{"method":"%s"}, %s}, "id": 1}' % (cat['method'], json.dumps(cat['properties']), cat['sort'], rule))
        json_response = json.loads(json_query)
        listitems = []      #搜索结果items列表
        actors = {}         #演员字典，key为艺人名字，value为字典，key为头像和次数。
        directors = {}      #导演字典
        if self.level > 1:      #什么情况会level<=1。哦，_fetch_items时level初始化为1. 
            #listitem即这一本电影的信息
            #当level>1时生成这个listitem加入的目的是什么？感觉是个空的listitem?
            listitem = xbmcgui.ListItem('..', offscreen=True)       #..是返回上一级的意思？
            listitem.setArt({'icon':'DefaultFolderBack.png'})
            listitems.append(listitem)
        if 'result' in json_response and(json_response['result'] != None) and cat['content'] in json_response['result']:
            for item in json_response['result'][cat['content']]:        #返回的items遍历
                if cat['type'] == 'actors' or cat['type'] == 'tvactors':    #元素类型为演员s
                    for item in item['cast']:                               #演员遍历
                        if search.lower() in item['name'].lower():          #返回结果全包含搜索串
                            name = item['name']                         #演员名字
                            if 'thumbnail' in item:                     #演员有头像
                                thumb = item['thumbnail']
                            else:
                                thumb = cat['icon']                     #演员没有头像，用类别的默认ICON
                            val = {}                                    #变量字典有两个key, 头像和次数。
                            val['thumb'] = thumb
                            if name in actors and 'count' in actors[name]:
                               val['count'] = actors[name]['count'] + 1
                            else:
                               val['count'] = 1
                            actors[name] = val
                elif cat['type'] == 'directors':                            #元素类型为导演s
                    for item in item['director']:                           #导演遍历
                        if search.lower() in item.lower():                  #处理流程同演员
                            name = item
                            val = {}
                            val['thumb'] = cat['icon']
                            if name in directors and 'count' in directors[name]:
                               val['count'] = directors[name]['count'] + 1
                            else:
                               val['count'] = 1
                            directors[name] = val
                else:
                    #不是演员和导演，创建一个标准内置的ListItem
                    listitem = xbmcgui.ListItem(item['label'], offscreen=True)      #title为返回元素的label
                    listitem.setArt(self._get_art(item, cat['icon'], cat['media'])) #图片为返回元素的封面图(poster.jpg优先级最高)
                if cat['streamdetails']:        #需要收集媒体编码率等信息
                    for stream in item['streamdetails']['video']:
                        listitem.addStreamInfo('video', stream)
                    for stream in item['streamdetails']['audio']:
                        listitem.addStreamInfo('audio', stream)
                    for stream in item['streamdetails']['subtitle']:
                        listitem.addStreamInfo('subtitle', stream)
                if cat['type'] != 'actors' and cat['type'] != 'directors' and cat['type'] != 'tvactors':
                    #type不是人，就加入conent类型。
                    listitem.setProperty('content', cat['content'])
                if cat['content'] == 'tvshows' and cat['type'] != 'tvactors':
                    #电视剧，加入总季数，总集数，已观看集数，未观看集数属性
                    listitem.setProperty('TotalSeasons', str(item['season']))
                    listitem.setProperty('TotalEpisodes', str(item['episode']))
                    listitem.setProperty('WatchedEpisodes', str(item['watchedepisodes']))
                    listitem.setProperty('UnWatchedEpisodes', str(item['episode'] - item['watchedepisodes']))
                elif cat['content'] == 'seasons':
                    #季，放入电视剧ID属性
                    listitem.setProperty('tvshowid', str(item['tvshowid']))
                elif (cat['content'] == 'movies' and cat['type'] != 'actors' and cat['type'] != 'directors') or cat['content'] == 'episodes' or cat['content'] == 'musicvideos':
                    #内容基准是电影/视频，放入历史播放时间点属性
                    listitem.setProperty('resume', str(int(item['resume']['position'])))
                elif cat['content'] == 'artists' or cat['content'] == 'albums':
                    #音乐相关信息
                    info, props = self._split_labels(item, cat['properties'], cat['content'][0:-1] + '_')
                    for key, value in props.items():
                        listitem.setProperty(key, value)
                if cat['content'] == 'albums':
                    #专辑，放入艺人ID属性
                    listitem.setProperty('artistid', str(item['artistid'][0]))
                if cat['content'] == 'songs':
                    #歌曲，放入专辑ID和艺人ID属性
                    listitem.setProperty('artistid', str(item['artistid'][0]))
                    listitem.setProperty('albumid', str(item['albumid']))
                if (cat['content'] == 'movies' and cat['type'] != 'actors' and cat['type'] != 'directors') or (cat['content'] == 'tvshows' and cat['type'] != 'tvactors') or cat['content'] == 'episodes' or cat['content'] == 'musicvideos' or cat['content'] == 'songs':
                    #加入实体路径属性
                    listitem.setPath(item['file'])
                if cat['media']:        #video/audio/null
                    listitem.setInfo(cat['media'], self._get_info(item, cat['content'][0:-1]))
                    listitem.setProperty('media', cat['media'])         #媒体类型
                if cat['content'] == 'tvshows' and cat['type'] != 'tvactors':
                    listitem.setIsFolder(True)      #item对应的是目录而非文件
                if cat['type'] != 'actors' and cat['type'] != 'directors' and cat['type'] != 'tvactors':
                    listitems.append(listitem)      #item加入到listitems
            if actors:      #演员字典里有数据
                for name, val in sorted(actors.items()):    #遍历演员字典
                    listitem = xbmcgui.ListItem(name, str(val['count']), offscreen=True)
                    listitem.setArt({'icon':cat['icon'], 'thumb':val['thumb']})
                    listitem.setProperty('content', cat['type'])
                    listitems.append(listitem)              #演员也作为一个item加入到listitems
            if directors:   #导演字典里有数据
                for name, val in sorted(directors.items()): #遍历导演字典
                    listitem = xbmcgui.ListItem(name, str(val['count']), offscreen=True)
                    listitem.setArt({'icon':cat['icon'], 'thumb':val['thumb']})
                    listitem.setProperty('content', cat['type'])
                    listitems.append(listitem)              #导演也作为一个item加入到listitems
        if len(listitems) > 0:
            if self.level > 1:
                numitems = str(len(listitems) - 1)
            else:
                numitems = str(len(listitems))
            #第一个构建参数label为显示内容
            #numitems作为隐藏的label2
            #offscreen=True，GUI离线创建。提高性能。
            if cat['type'] != 'actors' and cat['type'] != 'tvactors': 
                menuitem = xbmcgui.ListItem(xbmc.getLocalizedString(cat['label']), numitems, offscreen=True)
            else:
                menuitem = xbmcgui.ListItem(LANGUAGE(cat['label']), numitems, offscreen=True)
            #menuitem也是一个ListItem? menuitem是什么鬼？
            #对所有返回只创建了一个menu listitem
            menuitem.setArt({'icon':cat['menuthumb']})      #演员/导演的默认头像
            menuitem.setProperty('type', cat['type'])
            if cat['type'] != 'actors' and cat['type'] != 'directors' and cat['type'] != 'tvactors':
                menuitem.setProperty('content', cat['content'])
            elif cat['type'] == 'actors' or cat['type'] == 'tvactors':
                menuitem.setProperty('content', 'actors')
            elif cat['type'] == 'directors':
                menuitem.setProperty('content', 'directors')
            #menuitem有content属性和type属性。
            self.menu.addItem(menuitem)     #加入到menu
            if self.navback:                #有上一页？self.navback什么时候被置位？
                self.menu.selectItem(self.history[self.level]['menuposition'])
            self.content[cat['type']] = listitems
            if self.navback and self.focusset == 'false':
                if self.history[self.level]['menutype'] == cat['type']:
                    if cat['type'] != 'actors' and cat['type'] != 'directors' and cat['type'] != 'tvactors':
                        self.setContent(cat['content'])
                    elif cat['type'] == 'actors' or cat['type'] == 'tvactors':
                        self.setContent('actors')
                    elif cat['type'] == 'directors':
                        self.setContent('directors')
                    self.addItems(listitems)            #把查询结果的ListItems加入到窗口UI
                    # wait for items to be added before we can set focus
                    xbmc.sleep(100)
                    self.setCurrentListPosition(self.history[self.level]['containerposition'])      #有上一页需要定位？
                    self.menutype = cat['type']
                    self.focusset = 'true'              #focusset标志置位TRUE
            elif self.focusset == 'false':
                if cat['type'] != 'actors' and cat['type'] != 'directors' and cat['type'] != 'tvactors':
                    self.setContent(cat['content'])
                elif cat['type'] == 'actors' or cat['type'] == 'tvactors':
                    self.setContent('actors')
                elif cat['type'] == 'directors':
                    self.setContent('directors')        #把查询结果的ListItems加入到窗口UI
                self.addItems(listitems)
                # wait for items to be added before we can set focus
                xbmc.sleep(100)
                self.setFocusId(self.getCurrentContainerId())
                self.menutype = cat['type']
                self.focusset = 'true'                  #focusset标志置位TRUE
    #搜索流媒体频道组？
    def _fetch_channelgroups(self, cat):
        self.getControl(SEARCHCATEGORY).setLabel(xbmc.getLocalizedString(19069))
        self.getControl(SEARCHCATEGORY).setVisible(True)
        channelgrouplist = []       #频道组列表
        json_query = xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"PVR.GetChannelGroups", "params":{"channeltype":"tv"}, "id":1}')
        json_response = json.loads(json_query)
        if('result' in json_response) and(json_response['result'] != None) and('channelgroups' in json_response['result']):
            for item in json_response['result']['channelgroups']:
                channelgrouplist.append(item['channelgroupid'])
            if channelgrouplist:        #存在流媒体组
                self._fetch_channels(cat, channelgrouplist)

    def _fetch_channels(self, cat, channelgrouplist):
        # get all channel id's
        channellist = []        #频道列表
        for channelgroupid in channelgrouplist:     #组遍历
            #查询这个组内的频道
            json_query = xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"PVR.GetChannels", "params":{"channelgroupid":%i, "properties":["channel", "thumbnail"]}, "id":1}' % channelgroupid)
            json_response = json.loads(json_query)
            if('result' in json_response) and(json_response['result'] != None) and('channels' in json_response['result']):
                for item in json_response['result']['channels']:
                    channellist.append(item)        #添加这个频道
        if channellist:     #频道列表里有ITEM
            # remove duplicates
            channels = [dict(tuples) for tuples in set(tuple(item.items()) for item in channellist)]    #删除重复的频道
            # sort
            channels.sort(key=operator.itemgetter('channelid')) 
            self._fetch_livetv(cat, channels)           #检索每个频道的详细信息

    def _fetch_livetv(self, cat, channels):
        listitems = []
        # get all programs for every channel id
        for channel in channels:            #频道遍历
            channelid = channel['channelid']    #频道ID
            channelname = channel['label']      #频道title
            channelthumb = channel['thumbnail']     #频道图标
            json_query = xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"PVR.GetBroadcasts", "params":{"channelid":%i, "properties":["starttime", "endtime", "runtime", "genre", "plot"]}, "id":1}' % channelid)
            json_response = json.loads(json_query)
            if('result' in json_response) and(json_response['result'] != None) and('broadcasts' in json_response['result']):
                #一个频道内又有多个broadcast? 晕了... 意思是一个频道内有多个节目？ 比如杭州民生频道是channel, 1818黄金眼是broadcast。
                for item in json_response['result']['broadcasts']:      
                    broadcastname = item['label']           #节目名称
                    livetvmatch = re.search('.*' + self.searchstring + '.*', broadcastname, re.I)   
                    if livetvmatch:         #节目名称跟搜索串匹配
                        broadcastid = item['broadcastid']   #节目ID
                        duration = item['runtime']          #时长
                        genre = item['genre'][0]            #风格
                        plot = item['plot']                 #节目简介
                        starttime = item['starttime']       #开始时间
                        endtime = item['endtime']           #结束时间
                        listitem = xbmcgui.ListItem(label=broadcastname, offscreen=True)
                        listitem.setArt({'icon':'DefaultFolder.png', 'thumb':channelthumb})
                        listitem.setProperty("icon", channelthumb)
                        listitem.setProperty("genre", genre)
                        listitem.setProperty("plot", plot)
                        listitem.setProperty("starttime", starttime)
                        listitem.setProperty("endtime", endtime)
                        listitem.setProperty("duration", str(duration))
                        listitem.setProperty("channelname", channelname)
                        listitem.setProperty("dbid", str(channelid))
                        listitems.append(listitem)          #该节目加入到ListItems
        if len(listitems) > 0:          #listitems里有内容
            #创建一个menu类型的listitem
            menuitem = xbmcgui.ListItem(xbmc.getLocalizedString(cat['label']), offscreen=True)
            menuitem.setArt({'icon':cat['menuthumb']})
            menuitem.setProperty('type', cat['type'])
            menuitem.setProperty('content', cat['content'])
            self.menu.addItem(menuitem)         #加入到menu
            #什么意思？self.content是一个不同内容分类的暂存器？
            #type会取得类型字符串，比如“movies/tvshows”
            #所以意思是设置当前的内容类型
            self.content[cat['type']] = listitems       
            if self.focusset == 'false':
                self.setContent(cat['content'])
                self.addItems(listitems)        #listitems附加到窗口UI
                # wait for items to be added before we can set focus
                xbmc.sleep(100)
                self.setFocusId(self.getCurrentContainerId())       #加入listitems到UI后要重新置位Focus?
                self.focusset = 'true'

    #清除已有的数据list，然后用content作为窗口新的content，并以item为索引把content中的itemlists加入到当前窗口UI?
    #参数content为字符串，如“movies/tvshows/videos”
    #参数item是defs.py里category的type，也是字符串，有时跟content一样，有时不一样（比如content为movie, type为actor）
    def _update_list(self, item, content):
        self.clearList()    #清除当前窗口的数据
        # we need some sleep, else the correct container layout won't be loaded
        xbmc.sleep(2)
        #设置窗口的内容容器的类型, 参数为字符串
        self.setContent(content)
        xbmc.sleep(2)
        #这里本质是切换，所以没有置位self.focusset为TRUE，是这个意思吗？
        self.addItems(self.content[item])           
    #item是categories里的type字符串，“movie/tvshow/actor/episode...”
    #labels是一个字典？ 可以把labels看作是所有不同类型item属性的一个超集？
    #这个函数是什么用处？？？
    def _get_info(self, labels, item):
        labels['mediatype'] = item
        labels['dbid'] = labels['%sid' % item]
        del labels['%sid' % item]
        if item == 'season' or item == 'artist':
            labels['title'] = labels['label']
        del labels['label']
        if item != 'artist' and item != 'album' and item != 'song' and item != 'livetv':
            del labels['art']
        elif item == 'artist' or item == 'album' or item == 'song':
            del labels['art']
            del labels['thumbnail']
            del labels['fanart']
        else:
            del labels['thumbnail']
            del labels['fanart']
        if item == 'movie' or item == 'tvshow' or item == 'episode' or item == 'musicvideo':
            labels['duration'] = labels['runtime']
            labels['path'] = labels['file']
            del labels['file']
            del labels['runtime']
            if item != 'tvshow':
                del labels['streamdetails']
                del labels['resume']
            else:
                del labels['watchedepisodes']
        if item == 'season' or item == 'episode':
            labels['tvshowtitle'] = labels['showtitle']
            del labels['showtitle']
            if item == 'season':
                del labels['tvshowid']
                del labels['watchedepisodes']
            else:
                labels['aired'] = labels['firstaired']
                del labels['firstaired']
        if item == 'album':
            labels['album'] = labels['title']
            del labels['artistid']
        if item == 'song':
            labels['tracknumber'] = labels['track']
            del labels['track']
            del labels['file']
            del labels['artistid']
            del labels['albumid']
        for key, value in labels.items():
            if isinstance(value, list):
                if key == 'artist' and item == 'musicvideo':
                    continue
                value = " / ".join(value)
            labels[key] = value
        return labels
    #media为'video/music/picture/game'？
    #获取item的图片（poster/fanart/...）
    #字典形式返回媒介（media）的图片集
    def _get_art(self, labels, icon, media):
        if media == 'video':
            art = labels['art']
            if labels.get('poster'):
                art['thumb'] = labels['poster']
            elif labels.get('banner'):
                art['thumb'] = labels['banner']
            # needed for seasons and episodes
            elif art.get('tvshow.fanart'):
               art['fanart'] = art['tvshow.fanart']
        else:
            art = labels['art']
            # needed for albums and songs
            art['thumb'] = labels['thumbnail']
            art['fanart'] = labels['fanart']
        art['icon'] = icon
        return art
    #用在什么地方？
    def _split_labels(self, item, labels, prefix):
        props = {}      #属性集？
        for label in labels:
            if label == 'thumbnail' or label == 'fanart' or label == 'art' or label == 'rating' or label == 'userrating' or label == 'title' or label == 'file' or label == 'artistid' or label == 'albumid' or label == 'songid' or (prefix == 'album_' and (label == 'artist' or label == 'genre' or label == 'year')):
                continue
            if isinstance(item[label], list):           #item[label]是列表
                item[label] = " / ".join(item[label])   #把这个列表中的字符串用/连接
            if label == 'albumlabel':
                props[prefix + 'label'] = item['albumlabel']
            else:
                props[prefix + label] = item[label]     #在props字典里key加了前缀
            del item[label]
        return item, props
    #字符串转义标准化
    def _clean_string(self, string):
        return string.replace('(', '[(]').replace(')', '[)]').replace('+', '[+]')
    #key都是二级关联属性？比如艺人的专辑，电视剧的季
    def _get_allitems(self, key, listitem):
        if key == 'tvshowseasons':
            search = listitem.getVideoInfoTag().getDbId()
        elif key == 'seasonepisodes':
            tvshow = listitem.getProperty('tvshowid')
            season = listitem.getVideoInfoTag().getSeason()
            search = [tvshow, season]
        elif key == 'artistalbums':
            search = listitem.getMusicInfoTag().getDbId()
        elif key == 'albumsongs':
            search = listitem.getMusicInfoTag().getDbId()
        elif key == 'actormovies' or key == 'directormovies' or key == 'actortvshows':
            search = listitem.getLabel()
        #至此，生成了搜索的元数据
        #变量复位
        self._reset_variables()
        #所有控件隐藏
        self._hide_controls()
        #数据清除
        self.clearList()
        #菜单复位
        self.menu.reset()
        self.oldfocus = 0
        self.level += 1         #这个level起什么作用？
        #在history里记录之前的菜单位置/菜单类型/容器位置
        self.history[self.level - 1]['menuposition']  = self.menuposition
        self.history[self.level - 1]['menutype']  = self.menutype
        self.history[self.level - 1]['containerposition']  = self.containerposition
        #在history里记录当前的category和搜索串
        self.history[self.level] = {'cats':[CATEGORIES[key]], 'search':search,}
        #用jsonrpc从kodi主程序获取数据
        self._get_items(CATEGORIES[key], search)
        #这个函数做什么用？
        self._check_focus()
    
    #action某个元素，可能为显示详细信息也可能播放
    #如播放，则调用系统的jsonrpc来完成。
    def _play_item(self, key, value, listitem=None):
        #key为（视频）文件？
        if key == 'file':
            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"Player.Open", "params":{"item":{"%s":"%s"}}, "id":1}' % (key, value))
        #key为专辑ID或歌曲ID
        elif key == 'albumid' or key == 'songid':
            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"Player.Open", "params":{"item":{"%s":%d}}, "id":1}' % (key, int(value)))
        else:
            resume = int(listitem.getProperty('resume'))    #获取历史时间点
            selected = False
            if self.playaction == 0:
                labels = ()
                functions = ()
                if int(resume) > 0:                         #曾经播放到一半
                    m, s = divmod(resume, 60)
                    h, m = divmod(m, 60)
                    val = '%d:%02d:%02d' % (h, m, s)
                    labels += (LANGUAGE(32212) % val,)                      #LANGUAGE(32212)=Resume from %s. 在脚本自带的strings.po里
                    functions += ('resume',)
                    labels += (xbmc.getLocalizedString(12021),)             #12021=Play from beginning
                    functions += ('play',)
                else:       #从头播放
                    labels += (xbmc.getLocalizedString(208),)               #208=Play
                    functions += ('play',)
                labels += (xbmc.getLocalizedString(22081),)                 #22081=Show information
                functions += ('info',)
                selection = xbmcgui.Dialog().contextmenu(labels)            #弹出上下文菜单？labels是给上下文菜单的输入？
                if selection >= 0:      #用户选择了上下文菜单的某项
                    selected = True
                    if functions[selection] == 'play':      #选择从头播放
                        self.playaction = 1
                    elif functions[selection] == 'resume':  #选择继续播放
                        self.playaction = 2
                    elif functions[selection] == 'info':    #选择查看信息
                        self.playaction = 3
            #playaction=1, 从头播放
            #playaction=2，继续播放
            #playaction=3, 查看信息
            if self.playaction == 3:
                self._show_info(listitem)       #显示item的详细信息页
            elif self.playaction == 1 or self.playaction == 2:      #播放
                if self.playaction == 1 and not selected:           #从头播放且什么，什么意思？？？
                    if int(resume) > 0:                             #之前曾经播放到一半
                        labels = ()
                        functions = ()
                        m, s = divmod(resume, 60)
                        h, m = divmod(m, 60)
                        val = '%d:%02d:%02d' % (h, m, s)
                        labels += (LANGUAGE(32212) % val,)                  #LANGUAGE(32212)=Resume from %s. 在脚本自带的strings.po里
                        functions += ('resume',)
                        labels += (xbmc.getLocalizedString(12021),)         #12021=Play from beginning
                        functions += ('play',)
                        selection = xbmcgui.Dialog().contextmenu(labels)    #再弹出一次上下文菜单？？？ 这是二次确认的意思？
                        if functions[selection] == 'resume':                #用户选择继续播放
                            self.playaction = 2                             #置标志位
                if self.playaction == 2:                            #继续播放
                    self.Player.resume = resume                     #resume点
                #奇怪，最终还是调系统的jsonrpc来播放，那self.Player的resume置位有什么用呢？
                #难道系统的player还是会来获取self.Player的数据？
                xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"Player.Open", "params":{"item":{"%s":%d}}, "id":1}' % (key, int(value)))

    #搜索无结果后的处理？
    def _check_focus(self):
        self.getControl(SEARCHCATEGORY).setVisible(False)   #搜索的分类结果控件隐藏
        self.getControl(SEARCHBUTTON).setVisible(True)      #搜索BUTTON显示
        if self.focusset == 'false':                        #所以focusset==false，就是搜索没有结果？
            self.getControl(NORESULTS).setVisible(True)     #搜索无结果LABEL显示
            self.setFocus(self.getControl(SEARCHBUTTON))    #焦点放在搜索BUTTON上
            dialog = xbmcgui.Dialog()
            #284="No results found"
            #LANGUAGE(32298)="Search again?"
            ret = dialog.yesno(xbmc.getLocalizedString(284), LANGUAGE(32298))       #弹出YESNO对话框，是否要进行新的搜索？
            if ret:     #用户选择新搜索
                self._new_search()
            else:       #用户放弃
                self._close()

    #弹出listitem的上下文菜单？
    def _context_menu(self, controlId, listitem):
        labels = ()
        functions = ()
        media = ''          #'movie/tvshow/...'
        if listitem.getProperty('media') == 'video':
            media = listitem.getVideoInfoTag().getMediaType()
        elif listitem.getProperty('media') == 'music':
            media = listitem.getMusicInfoTag().getMediaType()
        if media == 'movie':
            labels += (xbmc.getLocalizedString(13346),)         #13346="Movie information"
            functions += ('info',)
            path = listitem.getVideoInfoTag().getTrailer()      #是否存在预告片
            if path:
                labels += (LANGUAGE(32205),)                    #32205=Play trailer（播放预告片）
                functions += ('play',)
        elif media == 'tvshow':
            #20351=“TV show information”
            #LANGUAGE(32207)=“Find all seasons”（“查找整季”）
            #LANGUAGE(32208)=“Find all episodes”（“查找所有分集”）
            labels += (xbmc.getLocalizedString(20351), LANGUAGE(32207), LANGUAGE(32208),)
            functions += ('info', 'tvshowseasons', 'tvshowepisodes',)
        elif media == 'episode':
            labels += (xbmc.getLocalizedString(20352),)         #20352="Episode information"
            functions += ('info',)
        elif media == 'musicvideo':
            labels += (xbmc.getLocalizedString(20393),)         #20393="Music video information"
            functions += ('info',)
        elif media == 'artist':
            #21891="Artist information"
            #LANGUAGE(32209)="Find all albums"（“查找所有专辑”）
            #LANGUAGE(32210)="Find all songs"（“查找所有歌曲”）
            labels += (xbmc.getLocalizedString(21891), LANGUAGE(32209), LANGUAGE(32210),)
            functions += ('info', 'artistalbums', 'artistsongs',)
        elif media == 'album':
            #13351="Album information"
            labels += (xbmc.getLocalizedString(13351),)
            functions += ('info',)
            #208="Play"
            labels += (xbmc.getLocalizedString(208),)
            functions += ('play',)
        elif media == 'song':
            #658="Song information"
            labels += (xbmc.getLocalizedString(658),)
            functions += ('info',)
        if listitem.getProperty('type') != 'livetv':
            if listitem.getProperty('content') in ('movies', 'episodes', 'musicvideos', 'songs'):
                path = listitem. getPath()
            elif listitem.getProperty('content') == 'tvshows':
                dbid = listitem.getVideoInfoTag().getDbId()
                path = "videodb://tvshows/titles/%s/" % dbid
            elif listitem.getProperty('content') == 'seasons':
                dbid = listitem.getVideoInfoTag().getSeason()
                tvshowid = listitem.getProperty('tvshowid')
                path = "videodb://tvshows/titles/%s/%s/?tvshowid=%s" % (tvshowid, dbid, tvshowid)
            elif listitem.getProperty('content') == 'artists':
                dbid = listitem.getMusicInfoTag().getDbId()
                path = "musicdb://artists/%s/?albumartistsonly=%s" % (dbid, self.albumartists)
            elif listitem.getProperty('content') == 'albums':
                dbid = listitem.getMusicInfoTag().getDbId()
                artistid = listitem.getProperty('artistid')
                path = "musicdb://artists/%s/%s/?albumartistsonly=%s&artistid=%s" % (artistid, dbid, self.albumartists, artistid)
            if path in self.favourites:
                #14077="Remove from favourites"
                labels += (xbmc.getLocalizedString(14077),)
            else:
                #14076="Add to favourites"
                labels += (xbmc.getLocalizedString(14076),)
            functions += ('favourite',)
        if labels:
            selection = xbmcgui.Dialog().contextmenu(labels)    #弹出上下文菜单
            if selection >= 0:                                  #用户选择了某项
                if functions[selection] == 'info':              #查看信息
                    self._show_info(listitem)
                elif functions[selection] == 'play':            #播放
                    if media != 'album':
                        self._play_item('file', path)
                    else:
                        self._play_item('albumid', dbid)
                elif functions[selection] == 'favourite':       #加入收藏
                    self._add_favourite(listitem)
                else:           #这个是什么动作？
                    self._get_allitems(functions[selection], listitem)
    #调用系统的dialog弹出显示某个item的详情
    def _show_info(self, listitem):
        xbmcgui.Dialog().info(listitem)

    #把listitem加入到收藏夹
    def _add_favourite(self, listitem):
        label = listitem.getLabel()
        thumbnail = listitem.getArt('poster')
        if not thumbnail:
            thumbnail = listitem.getArt('banner')
        if not thumbnail:
            thumbnail = listitem.getArt('thumb')
        if not thumbnail:
            thumbnail = listitem.getArt('icon')
        #listitem是可播放的物理实体
        if listitem.getProperty('content') in ('movies', 'episodes', 'musicvideos', 'songs'):
            #取得物理文件的系统路径
            path = listitem. getPath()
            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"Favourites.AddFavourite", "params":{"type":"media", "title":"%s", "path":"%s", "thumbnail":"%s"}, "id": 1}' % (label, path, thumbnail))
        elif listitem.getProperty('content') == 'tvshows':      #虚体则取虚体的dbid

            dbid = listitem.getVideoInfoTag().getDbId()
            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"Favourites.AddFavourite", "params":{"type":"window", "window":"10025", "windowparameter":"videodb://tvshows/titles/%s/", "title":"%s", "thumbnail":"%s"}, "id": 1}' % (dbid, label, thumbnail))
        elif listitem.getProperty('content') == 'seasons':
            dbid = listitem.getVideoInfoTag().getSeason()
            tvshowid = listitem.getProperty('tvshowid')
            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"Favourites.AddFavourite", "params":{"type":"window", "window":"10025", "windowparameter":"videodb://tvshows/titles/%s/%s/?tvshowid=%s", "title":"%s", "thumbnail":"%s"}, "id": 1}' % (tvshowid, dbid, tvshowid, label, thumbnail))
        elif listitem.getProperty('content') == 'artists':
            dbid = listitem.getMusicInfoTag().getDbId()
            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"Favourites.AddFavourite", "params":{"type":"window", "window":"10502", "windowparameter":"musicdb://artists/%s/?albumartistsonly=%s", "title":"%s", "thumbnail":"%s"}, "id": 1}' % (dbid, self.albumartists, label, thumbnail))
        elif listitem.getProperty('content') == 'albums':
            dbid = listitem.getMusicInfoTag().getDbId()
            artistid = listitem.getProperty('artistid')
            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "method":"Favourites.AddFavourite", "params":{"type":"window", "window":"10502", "windowparameter":"musicdb://artists/%s/%s/?albumartistsonly=%s&artistid=%s", "title":"%s", "thumbnail":"%s"}, "id": 1}' % (artistid, dbid, self.albumartists, artistid, label, thumbnail))
        #重新load一遍
        self._load_favourites()
    
    #遥控器按“回退（<-），键盘按ESC”
    #返回上一级
    def _nav_back(self):
        self._reset_variables()     #focusset=false
        self._hide_controls()       #隐藏所有控件
        self.clearList()            #清除数据
        self.menu.reset()           #菜单复位
        self.oldfocus = 0
        #所以self.level保存的是上一级（的搜索串和媒体类型）？
        #是这样的，在调用_nav_back之前已经对level做了-1处理
        cats = self.history[self.level]['cats']
        search = self.history[self.level]['search']
        #self.navback是个过程锁标志？即通知别的线程在取数据中？
        self.navback = True
        for cat in cats:                        #分类遍历
            self._get_items(cat, search)        #从系统检索数据。所以每次回退都是重新从kodi的db fetch数据
        self.navback = False

    #开始新搜索
    def _new_search(self):
        #32101="Enter search string"（“输入搜索字符串”）
        #调用系统的输入对话框
        keyboard = xbmc.Keyboard('', LANGUAGE(32101), False)
        keyboard.doModal()
        if(keyboard.isConfirmed()):
            self.searchstring = keyboard.getText()      #获取输入对话框的文本
            self.menu.reset()       #菜单复位
            self.oldfocus = 0       #oldfocus是个什么东西？
            self.clearList()        #数据清除
            self.onInit()           #数据查询和加载

    #CLICK事件处理？
    def onClick(self, controlId):
        if controlId == self.getCurrentContainerId():       #数据容器的click事件
            self.containerposition = self.getCurrentListPosition()      #容器位置？
            listitem = self.getListItem(self.getCurrentListPosition())  #取得容器位置的item
            media = ''
            if listitem.getLabel() == '..':     #回退
                self.level -= 1                 #level减1是回退上一个层级的意思？
                self._nav_back()
                return
            #这个media其实是defs.py里categories的type的意思？
            if listitem.getVideoInfoTag().getMediaType():
                media = listitem.getVideoInfoTag().getMediaType()
            elif listitem.getMusicInfoTag().getMediaType():
                media = listitem.getMusicInfoTag().getMediaType()
            elif xbmc.getCondVisibility('Container.Content(actors)'):
                media = 'actors'
            elif xbmc.getCondVisibility('Container.Content(directors)'):
                media = 'directors'

            if media == 'movie':            #点击在电影上
                movieid = listitem.getVideoInfoTag().getDbId()
                self._play_item('movieid', movieid, listitem)           #action处理，一般的处理是弹出action菜单，让用户选择查看详情或者播放（从头播放/继续播放）
            elif media == 'tvshow':                                     #电视剧虚体，获取季信息
                self._get_allitems('tvshowseasons', listitem)
            elif media == 'season':                                     #季虚体，获取集信息
                self._get_allitems('seasonepisodes', listitem)
            elif media == 'episode':                                    #集实体，弹出action菜单
                episodeid = listitem.getVideoInfoTag().getDbId()
                self._play_item('episodeid', episodeid, listitem)
            elif media == 'musicvideo':                                 #音乐视频实体，弹出action菜单
                musicvideoid = listitem.getVideoInfoTag().getDbId()
                self._play_item('musicvideoid', musicvideoid, listitem)
            elif media == 'artist':                                     #艺人虚体，获取专辑信息
                self._get_allitems('artistalbums', listitem)
            elif media == 'album':                                      #专辑虚体，获取歌曲信息
                self._get_allitems('albumsongs', listitem)
            elif media == 'song':                                       #歌曲实体，直接播放
                songid = listitem.getMusicInfoTag().getDbId()
                self._play_item('songid', songid)
            elif media == 'actors':                                     #演员虚体
                content = listitem.getProperty('content')
                if content == 'actors':
                    self._get_allitems('actormovies', listitem)
                if content == 'tvactors':
                    self._get_allitems('actortvshows', listitem)
            elif media == 'directors':                                  #导演虚体
                self._get_allitems('directormovies', listitem)
        elif controlId == MENU:         #菜单的click事件(要看一下这个是什么菜单？)
            item = self.menu.getSelectedItem().getProperty('type')
            content = self.menu.getSelectedItem().getProperty('content')
            self.menuposition = self.menu.getSelectedPosition()
            self.menutype = self.menu.getSelectedItem().getProperty('type')
            self._update_list(item, content)
        elif controlId == SEARCHBUTTON:         #搜索按钮的click事件
            self._new_search()                  #启动新搜索

    #这个是被系统调用，在gui.py没有找到对这个函数的调用
    #返回TRUE为已经处理，返回FALSE由KODI来处理。
    def onAction(self, action):
        if action.getId() in ACTION_CANCEL_DIALOG:      #关闭窗口action
            self._close()       
        elif action.getId() in ACTION_CONTEXT_MENU or action.getId() in ACTION_SHOW_INFO:       #来自上下文菜单或者详情显示的action
            controlId = self.getFocusId()           #当前焦点所在的控件
            if controlId == self.getCurrentContainerId():       #当前焦点所在的控件为内容控件
                listitem = self.getListItem(self.getCurrentListPosition())      #获取焦点位置的item
                if action.getId() in ACTION_CONTEXT_MENU:               #来自上下文菜单的action
                    self._context_menu(controlId, listitem)             #弹出这个item的上下文菜单
                elif action.getId() in ACTION_SHOW_INFO:                #来自显示详情action
                    media = ''
                    if listitem.getVideoInfoTag().getMediaType():       #视频
                        media = listitem.getVideoInfoTag().getMediaType()
                    elif listitem.getMusicInfoTag().getMediaType():     #音频
                        media = listitem.getMusicInfoTag().getMediaType()
                    if media != '' and media != 'season':
                        self._show_info(listitem)                       #显示media的详情
        #ACTION_MOVE_LEFT = 1; ACTION_MOVE_RIGHT = 2;
        #ACTION_MOVE_UP = 3; ACTION_MOVE_DOWN = 4;
        #所以1/2/3/4是方向键的action
        #ACTION_MOUSE_MOVE = 107(鼠标移动action是什么，总不是rollover吧)
        #所以是焦点在菜单上，然后发生了方向和鼠标事件？
        elif self.getFocusId() == MENU and action.getId() in (1, 2, 3, 4, 107): 
            #获取菜单上元素的content和type
            item = self.menu.getSelectedItem().getProperty('type')
            content = self.menu.getSelectedItem().getProperty('content')
            self.menuposition = self.menu.getSelectedPosition()
            #self.menutype不就等于item吗？
            self.menutype = self.menu.getSelectedItem().getProperty('type')  
            #self.oldfocus只记录菜单上的item？ 对，oldfocus在别的地方都复位0，只有在这里有置位。
            if self.oldfocus and item != self.oldfocus:                 #在item上发生了焦点切换
                self.oldfocus = item
                self._update_list(item, content)                        #这句的目的是什么？？？
            else:       #内容控件第一次获取焦点？
                self.oldfocus = item

    #关闭当前窗口？.
    def _close(self):
        ADDON.setSettingInt('view', self.getCurrentContainerId())       #这句什么意思？当前容器ID保存？
        xbmcgui.Window(self.window_id).clearProperty('GlobalSearch.SearchString')   #清除搜索串属性
        self.close()            #物理关闭窗口？
        log('script stopped')

#其实是系统的内置播放器实例？
class MyPlayer(xbmc.Player):
    def __init__(self, *args, **kwargs):
        xbmc.Player.__init__(self)
        self.resume = 0         #增加了一个resume参数，即上次播放的时间点
    
    #如有历史播放时间点，定位
    def onAVStarted(self):
        if self.resume > 0:
            self.seekTime(float(self.resume))
